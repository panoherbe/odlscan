"""Tests ohne Netz: synthetische Reihen und kleine Beispieldateien im Format der Quellen."""

import gzip
import json
import zipfile

import numpy as np
import pytest

from odlscan import anomalie, bewertung, einlesen, geo, quellen, trend


def reihe(n=168, niveau=0.08, rausch=0.0015, seed=1):
    rng = np.random.default_rng(seed)
    return np.round(niveau + rng.normal(0, rausch, n), 3)


def test_abstand_hamburg_berlin():
    d = geo.abstand_km([53.55], [9.99], [52.52], [13.40])[0, 0]
    assert 250 < d < 260


def test_nachbarn_hoehe():
    nb = geo.nachbarn([50.0, 50.1, 50.2], [8.0, 8.0, 8.0], 30, hoehe=[100, 150, 900], max_hoehendiff=300)
    assert list(nb[0]) == [1] and list(nb[2]) == []


def test_ruhige_reihe_ohne_meldung():
    e = anomalie.erkennen(reihe())
    assert not e["oben"].any() and not e["unten"].any() and not e["haenger"].any()


def test_spitze_stufe_absenkung_haenger():
    x = reihe()
    y, a, b = bewertung.einbauen(x, "spitze", 100, 0.5)
    assert anomalie.erkennen(y)["oben"][100]
    y, a, b = bewertung.einbauen(x, "stufe", 100, 0.2)
    assert anomalie.erkennen(y)["oben"][a:b + 1].any()
    y, a, b = bewertung.einbauen(x, "absenkung", 100, 0.2)
    assert anomalie.erkennen(y)["unten"][a:b + 1].any()
    y, a, b = bewertung.einbauen(x, "haenger", 100, 0)
    assert anomalie.erkennen(y)["haenger"][100:112].all()


def test_basislinie_kausal():
    x = np.arange(48, dtype=float)
    b = anomalie.basislinie(x)
    assert np.isnan(b[:24]).all() and b[24] == np.median(x[:24])


def test_einordnung_regen_und_lokal():
    x = reihe()
    x[100] += 0.04
    regen = np.zeros((1, len(x)))
    regen[0, 99] = 1.2
    erg = [anomalie.erkennen(x)]
    ev = anomalie.alle_ereignisse(x[None], erg, regen, [np.array([], int)])
    assert [v["klasse"] for v in ev if v["art"] == "oben"] == ["regen"]
    ev = anomalie.alle_ereignisse(x[None], erg, np.zeros((1, len(x))), [np.array([], int)])
    assert [v["klasse"] for v in ev if v["art"] == "oben"] == ["lokal"]


def test_voralarm_zwei_nachbarn():
    a, b, c = reihe(seed=1), reihe(seed=2), reihe(seed=3)
    a[90] += 0.04
    b[91] += 0.04
    c[60] += 0.04
    erg = anomalie.erkennen_alle(np.array([a, b, c]))
    nb = geo.nachbarn([50.0, 50.1, 52.0], [8.0, 8.0, 8.0], 30)
    va = anomalie.voralarme(erg, np.zeros((3, len(a))), nb)
    assert len(va) == 1 and va[0]["sonden"] == 2


def test_voralarm_einordnung_nach_regenmesser():
    a, b = reihe(seed=1), reihe(seed=2)
    a[90] += 0.04
    b[91] += 0.04
    erg = anomalie.erkennen_alle(np.array([a, b]))
    nb = geo.nachbarn([50.0, 50.1], [8.0, 8.0], 30)
    ohne = anomalie.voralarme(erg, np.full((2, len(a)), np.nan), nb)
    trocken = anomalie.voralarme(erg, np.zeros((2, len(a))), nb)
    nass = np.zeros((2, len(a)))
    nass[:, 89:92] = 0.8
    regen = anomalie.voralarme(erg, nass, nb)
    # fehlende Messerdaten zählen nicht als „kein Regen“
    assert [anomalie.voralarm_klasse(v) for v in ohne + trocken + regen] == ["ohne_messer", "trocken", "regen"]
    assert ohne[0]["messer_anteil"] == 0 and trocken[0]["trocken_anteil"] == 1


def test_referenz_korrelation_waehlt_aehnliche_nachbarn():
    rng = np.random.default_rng(8)
    gemeinsam = np.cumsum(rng.normal(0, 0.01, 365))
    logodl = np.array([gemeinsam + rng.normal(0, 0.002, 365) for _ in range(4)]
                      + [np.cumsum(rng.normal(0, 0.01, 365)) for _ in range(3)])
    kandidaten = [np.array([j for j in range(7) if j != i]) for i in range(7)]
    ref = trend.referenz_korrelation(logodl, kandidaten, anzahl=3)
    assert np.allclose(ref[0], np.median(logodl[1:4], axis=0))


def test_vergleichsvariante_aendert_die_zufallsfolge_nicht():
    rng = np.random.default_rng(9)
    logodl = rng.normal(np.log(0.1), 0.01, (30, 365))
    ref = logodl + rng.normal(0, 0.005, logodl.shape)
    schnee = np.zeros_like(logodl)
    strafe = {"roh": 3.0, "nachbarn": 3.0, "korrelation": 3.0}
    ohne = bewertung.tages_test(logodl, ref, schnee, strafe, durchlaeufe=2, je_lauf=10)
    mit = bewertung.tages_test(logodl, ref, schnee, strafe, durchlaeufe=2, je_lauf=10, ref_korrelation=ref)
    assert ohne["je_stufe"]["roh"] == mit["je_stufe"]["roh"]
    assert ohne["je_stufe"]["nachbarn"] == mit["je_stufe"]["nachbarn"]
    assert sum(z["n"] for z in mit["je_stufe"]["korrelation"].values()) == 20


def test_sprung_wird_gefunden():
    rng = np.random.default_rng(5)
    y = rng.normal(0, 0.01, 365)
    y[200:] += 0.05
    sp = trend.spruenge(y)
    assert len(sp) == 1 and abs(sp[0]["index"] - 200) <= 3 and sp[0]["hoehe"] > 0.04


def test_kein_sprung_im_rauschen():
    rng = np.random.default_rng(6)
    assert trend.spruenge(rng.normal(0, 0.01, 365)) == []


def test_schnee_effekt():
    odl = np.full((1, 120), 0.08)
    schnee = np.zeros((1, 120))
    odl[0, 60:70] = 0.068
    schnee[0, 60:70] = 10
    r = trend.schnee_effekt(odl, schnee)
    assert r["6–15 cm"]["tage"] == 10 and r["6–15 cm"]["median"] == pytest.approx(-0.15)


def test_bfs_json_und_dwd_zip(tmp_path):
    feat = lambda t, v: {"type": "Feature", "geometry": {"type": "Point", "coordinates": [9.38, 54.78]},  # noqa
                         "properties": {"id": "DEZ0001", "kenn": "010010001", "name": "Flensburg",
                                        "start_measure": t, "end_measure": t, "value": v, "validated": 1}}
    p = tmp_path / "r.json.gz"
    p.write_bytes(gzip.compress(json.dumps({"features": [feat("2026-11-02T01:00:00Z", 0.09),
                                                         feat("2026-11-02T00:00:00Z", 0.08)]}).encode()))
    t, v, g = einlesen.zeitreihe(p)
    assert list(v) == [0.08, 0.09] and str(t[0]) == "2026-11-02T00:00"
    z = tmp_path / "stundenwerte_RR_00044_akt.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("produkt_rr_stunde_20250501_20261101_00044.txt",
                   "STATIONS_ID;MESS_DATUM;QN_8;  R1;RS_IND;WRTR;eor\n"
                   "         44;2026110122;    1;   0.0;   0;-999;eor\n"
                   "         44;2026110123;    1;-999;   1;-999;eor\n")
    t, w = einlesen.dwd_produkt(z, ["R1"])
    assert str(t[0]) == "2026-11-01T22" and w["R1"][0] == 0 and np.isnan(w["R1"][1])


def test_dwd_stationen_und_listing():
    text = ("Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland Abgabe\n"
            "----------- --------- ---------\n"
            "00044 20070401 20261102             44     52.9336    8.2370 Großenkneten   Niedersachsen   Frei\n"
            ).encode("latin-1")
    st = einlesen.dwd_stationen(text)
    assert st[0]["id"] == 44 and st[0]["lat"] == pytest.approx(52.9336)
    listing = b'<a href="stundenwerte_RR_00044_akt.zip">x</a>'
    assert quellen.dwd_zips(listing, r"stundenwerte_RR_\d{5}_akt\.zip") == {44: "stundenwerte_RR_00044_akt.zip"}
    sonden = [{"kenn": "1", "lat": 52.95, "lon": 8.25}, {"kenn": "2", "lat": 50.0, "lon": 8.0}]
    assert quellen.naechste_dwd(sonden, st, {44: "x"}) == {"1": 44}


def test_kalibrierung_alarmbudget():
    rng = np.random.default_rng(7)
    reihen = [rng.normal(0, 0.01, 365) for _ in range(40)]
    for y in reihen[:4]:
        y[180:] += 0.05
    c = trend.kalibrieren(reihen, anteil=0.1)
    mit = [bool(trend.spruenge(y, strafe=c)) for y in reihen]
    assert sum(mit) <= 5 and all(mit[:4])
