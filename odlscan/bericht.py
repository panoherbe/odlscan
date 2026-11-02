"""Auswertung einer Rohablage: Kennzahlen (ergebnisse.json), Abbildungen und Bericht (BERICHT.md)."""

from __future__ import annotations

import csv
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import __version__, anomalie, bewertung, einlesen, geo, trend


def de(x, stellen: int = 1, prozent: bool = False) -> str:
    """Zahl im deutschen Format (Tausenderpunkt, Dezimalkomma)."""
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    if prozent:
        x = 100 * x
    s = f"{x:,.{stellen}f}".replace(",", "X").replace(".", ",").replace("X", ".").replace("-", "−")
    return s + (" %" if prozent else "")


def datum(t) -> str:
    return np.datetime_as_string(t, unit="D") if t is not None else "–"


def tdm(t) -> str:
    j, m, d = datum(t).split("-")
    return f"{d}.{m}.{j}"


def _abbildungen(aus: Path, ds, erg_h, ev, sp_test, st_test, schnee, beispiel) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    abb = aus / "abbildungen"
    abb.mkdir(parents=True, exist_ok=True)
    namen = []

    # 1 Karte der Sonden, Farbe = Median der Tageswerte
    med = np.nanmedian(ds.odl_d, axis=1)
    fig, ax = plt.subplots(figsize=(5.2, 6.2))
    sc = ax.scatter(ds.lon, ds.lat, c=med, s=6, cmap="viridis", vmin=np.nanpercentile(med, 2),
                    vmax=np.nanpercentile(med, 98))
    ax.set_aspect(1 / np.cos(np.radians(51)))
    ax.set_xlabel("Länge (°)")
    ax.set_ylabel("Breite (°)")
    ax.set_title(f"{de(int(np.isfinite(med).sum()), 0)} ODL-Sonden, Median der Tageswerte")
    fig.colorbar(sc, ax=ax, shrink=0.7, label="µSv/h")
    fig.tight_layout()
    fig.savefig(abb / "abb1_karte.png", dpi=160)
    plt.close(fig)
    namen.append("abb1_karte.png")

    # 2 Beispiel Regenereignis
    if beispiel is not None:
        i, t = beispiel
        a, b = max(0, t - 36), min(ds.odl_h.shape[1], t + 24)
        x = ds.odl_h[i, a:b]
        e = erg_h[i]
        zeit = ds.stunden[a:b].astype("datetime64[h]")
        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.plot(zeit, x, color="#1f4e79", lw=1.4, label="ODL (Stundenwert)")
        ax.plot(zeit, e["b"][a:b], color="#888", lw=1, ls="--", label="Basislinie (Median 24 h)")
        ax.plot(zeit, e["b"][a:b] + anomalie.Z_SCHWELLE * e["s"], color="#c00", lw=0.8, ls=":",
                label="Schwelle z = 4")
        ax.set_ylabel("µSv/h")
        ax2 = ax.twinx()
        ax2.bar(zeit, ds.regen_h[i, a:b], width=1 / 24, color="#6baed6", alpha=0.6, label="Niederschlag DWD")
        ax2.set_ylabel("mm/h")
        ax2.spines["top"].set_visible(False)
        s = ds.sonden[i]
        ax.set_title(f"{s['name']} ({s['kenn']}): Regen hebt die ODL kurz an")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(abb / "abb2_regen.png", dpi=160)
        plt.close(fig)
        namen.append("abb2_regen.png")

    # 3 Trefferquote Stunden
    fig, ax = plt.subplots(figsize=(7, 3.0))
    labels, werte = [], []
    for k, z in st_test["je_fehler"].items():
        art, g = k.split("|")
        name = {"spitze": "Spitze", "stufe": "Stufe", "drift": "Drift", "absenkung": "Absenkung", "haenger": "Hänger"}[art]
        labels.append(name if art == "haenger" else f"{name} {float(g) * 100:.0f} %")
        werte.append(100 * (z["trefferquote"] or 0))
    ax.bar(range(len(werte)), werte, color="#1f4e79")
    ax.set_xticks(range(len(werte)), labels, rotation=45, ha="right")
    ax.set_ylabel("Trefferquote (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Stundenwerte: eingebaute Fehler, die erkannt werden")
    fig.tight_layout()
    fig.savefig(abb / "abb3_stundentest.png", dpi=160)
    plt.close(fig)
    namen.append("abb3_stundentest.png")

    # 4 Sprungerkennung roh vs. gegen Nachbarn
    fig, ax = plt.subplots(figsize=(6, 3.0))
    for var, farbe, name in (("roh", "#999", "Reihe allein"), ("nachbarn", "#1f4e79", "gegen Nachbarn")):
        xs = [100 * float(s) for s in sp_test["je_stufe"][var]]
        ys = [100 * (z["trefferquote"] or 0) for z in sp_test["je_stufe"][var].values()]
        ax.plot(xs, ys, marker="o", color=farbe, label=name)
    ax.axhline(80, color="#c00", lw=0.7, ls=":")
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1, 2, 3, 5, 10], ["0,5", "1", "2", "3", "5", "10"])
    ax.set_xlabel("eingebaute Stufe (% der ODL)")
    ax.set_ylabel("Trefferquote (%)")
    ax.set_ylim(0, 105)
    ax.legend(fontsize=8)
    ax.set_title("Tageswerte: Sprungstellen (z. B. Sondenwechsel)")
    fig.tight_layout()
    fig.savefig(abb / "abb4_spruenge.png", dpi=160)
    plt.close(fig)
    namen.append("abb4_spruenge.png")

    # 5 Schnee
    klassen = [k for k in schnee if k != "schneefrei" and schnee[k]["tage"] > 0]
    if klassen:
        fig, ax = plt.subplots(figsize=(6, 3.0))
        daten = [100 * schnee["schneefrei"]["werte"]] + [100 * schnee[k]["werte"] for k in klassen]
        ax.boxplot(daten, showfliers=False)
        ax.set_xticks(range(1, len(daten) + 1), ["schneefrei"] + klassen)
        ax.axhline(0, color="#888", lw=0.7)
        ax.set_ylabel("Abweichung der Tages-ODL (%)")
        ax.set_xlabel("Schneehöhe an der nächsten DWD-Station")
        ax.set_title("Schneedecke schirmt die Bodenstrahlung ab")
        fig.tight_layout()
        fig.savefig(abb / "abb5_schnee.png", dpi=160)
        plt.close(fig)
        namen.append("abb5_schnee.png")
    return namen


def auswerten(raw: Path, aus: Path, durchlaeufe: int = 5, je_lauf: int = 300, abbildungen: bool = True) -> dict:
    uhr = {}
    t = time.perf_counter()
    ds = einlesen.Datensatz(raw)
    uhr["einlesen_s"] = time.perf_counter() - t
    n = len(ds.sonden)

    # Stundenwerte
    t = time.perf_counter()
    erg_h = anomalie.erkennen_alle(ds.odl_h)
    nb30 = geo.nachbarn(ds.lat, ds.lon, anomalie.VORALARM_KM)
    ev = anomalie.alle_ereignisse(ds.odl_h, erg_h, ds.regen_h, nb30)
    va = anomalie.voralarme(erg_h, ds.regen_h, nb30)
    uhr["stunden_pruefung_s"] = time.perf_counter() - t
    t = time.perf_counter()
    st_test = bewertung.stunden_test(ds.odl_h, erg_h, ds.regen_h, nb30, durchlaeufe, je_lauf)
    uhr["stunden_test_s"] = time.perf_counter() - t
    bewertet = int(sum(np.isfinite(e["z"]).sum() for e in erg_h))

    zaehl = {}
    for v in ev:
        zaehl[v["klasse"]] = zaehl.get(v["klasse"], 0) + 1
    oben = [v for v in ev if v["art"] == "oben"]
    oben_messer = [v for v in oben if v["messer"]]
    abkling = {k: [v["abkling"] for v in oben if v["klasse"] == k and np.isfinite(v["abkling"])]
               for k in ("regen", "regional", "lokal")}

    # Tageswerte
    t = time.perf_counter()
    with np.errstate(divide="ignore", invalid="ignore"):
        logodl = np.log(np.where(ds.odl_d > 0, ds.odl_d, np.nan))
    nb50 = geo.nachbarn(ds.lat, ds.lon, trend.NACHBAR_KM, ds.hoehe, trend.NACHBAR_DH)
    ref = trend.referenz(logodl, nb50)
    reihen = {"roh": [trend.reihe(logodl[i], None, ds.schnee_d[i]) for i in range(n)],
              "nachbarn": [trend.reihe(logodl[i], ref[i], ds.schnee_d[i]) for i in range(n)]}
    unkalibriert = {var: sum(bool(trend.spruenge(y)) for y in rs) for var, rs in reihen.items()}
    strafe = {var: trend.kalibrieren(rs) for var, rs in reihen.items()}
    kandidaten = {"roh": [], "nachbarn": []}
    for var, rs in reihen.items():
        for i, y in enumerate(rs):
            for p in trend.spruenge(y, strafe=strafe[var]):
                kandidaten[var].append({"sonde": i, **p})
    schnee = trend.schnee_effekt(ds.odl_d, ds.schnee_d)
    uhr["tage_pruefung_s"] = time.perf_counter() - t
    t = time.perf_counter()
    sp_test = bewertung.tages_test(logodl, ref, ds.schnee_d, strafe, durchlaeufe, je_lauf)
    uhr["tage_test_s"] = time.perf_counter() - t

    def mdc(var):
        for s, z in sp_test["je_stufe"][var].items():
            if (z["trefferquote"] or 0) >= 0.8:
                return float(s)
        return None

    med = np.nanmedian(ds.odl_d, axis=1)
    hat_h = np.isfinite(ds.odl_h).any(axis=1)
    hat_d = np.isfinite(ds.odl_d).any(axis=1)
    beispiel = None
    regen_ev = [v for v in oben if v["klasse"] == "regen" and v["messer"]]
    if regen_ev:
        v = max(regen_ev, key=lambda v: v["z"])
        beispiel = (v["sonde"], v["spitze"])

    ergebnisse = {
        "version": __version__,
        "ausgewertet": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rohablage": raw.name,
        "umgebung": {"python": sys.version.split()[0], "system": platform.platform(), "numpy": np.__version__},
        "daten": {
            "sonden_in_betrieb": n, "mit_stundenwerten": int(hat_h.sum()), "mit_tageswerten": int(hat_d.sum()),
            "stunden_von": str(ds.stunden[0]), "stunden_bis": str(ds.stunden[-1]), "stunden": len(ds.stunden),
            "tage_von": datum(ds.tage[0]), "tage_bis": datum(ds.tage[-1]), "tage": len(ds.tage),
            "stundenwerte": int(np.isfinite(ds.odl_h).sum()), "tageswerte": int(np.isfinite(ds.odl_d).sum()),
            "vollstaendig_stunden": float(np.isfinite(ds.odl_h[hat_h]).mean()),
            "vollstaendig_tage": float(np.isfinite(ds.odl_d[hat_d]).mean()),
            "odl_median": float(np.nanmedian(med)), "odl_p5": float(np.nanpercentile(med, 5)),
            "odl_p95": float(np.nanpercentile(med, 95)), "odl_min": float(np.nanmin(med)),
            "odl_max": float(np.nanmax(med)),
            "mit_regenmesser_stunde": int(np.isfinite(ds.regen_h).any(axis=1).sum()),
            "mit_schneemessung_tag": int(np.isfinite(ds.schnee_d).any(axis=1).sum()),
        },
        "stunden": {
            "bewertete_stundenwerte": bewertet,
            "ereignisse": zaehl,
            "je_1000_stundenwerte": {k: 1000 * v / bewertet for k, v in zaehl.items()},
            "erhoehungen_mit_regenmesser": len(oben_messer),
            "anteil_regen_an_erhoehungen_mit_messer": (sum(v["klasse"] == "regen" for v in oben_messer)
                                                       / len(oben_messer)) if oben_messer else None,
            "abkling_median": {k: float(np.median(v)) if v else None for k, v in abkling.items()},
            "abkling_n": {k: len(v) for k, v in abkling.items()},
            "voralarme": len(va),
            "voralarme_regen_ueberwiegend": sum(v["regen_anteil"] >= 0.5 for v in va),
            "voralarme_sonden_median": float(np.median([v["sonden"] for v in va])) if va else None,
            "test": st_test,
        },
        "tage": {
            "kandidaten_roh": len(kandidaten["roh"]),
            "kandidaten_nachbarn": len(kandidaten["nachbarn"]),
            "sonden_mit_kandidat_roh": len({k["sonde"] for k in kandidaten["roh"]}),
            "sonden_mit_kandidat_nachbarn": len({k["sonde"] for k in kandidaten["nachbarn"]}),
            "sonden_mit_referenz": int(np.isfinite(ref).any(axis=1).sum()),
            "alarm_anteil": trend.ALARM_ANTEIL, "strafe_kalibriert": strafe,
            "sonden_mit_sprung_bei_strafe_3": unkalibriert,
            "kleinste_stufe_80_roh": mdc("roh"), "kleinste_stufe_80_nachbarn": mdc("nachbarn"),
            "test": sp_test,
            "schnee": {k: {kk: vv for kk, vv in v.items() if kk != "werte"} for k, v in schnee.items()},
        },
        "laufzeit_s": uhr,
    }
    aus.mkdir(parents=True, exist_ok=True)
    (aus / "ergebnisse.json").write_text(json.dumps(ergebnisse, indent=1, ensure_ascii=False, default=float),
                                         encoding="utf-8")
    with open(aus / "ereignisse_stunden.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kenn", "name", "art", "klasse", "von_utc", "bis_utc", "z", "abkling", "regenmesser"])
        for v in ev:
            s = ds.sonden[v["sonde"]]
            w.writerow([s["kenn"], s["name"], v["art"], v["klasse"], ds.stunden[v["von"]], ds.stunden[v["bis"]],
                        f"{v['z']:.1f}", f"{v['abkling']:.2f}", int(v["messer"])])
    with open(aus / "sprungkandidaten.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kenn", "name", "variante", "tag", "stufe_prozent"])
        for var, ks in kandidaten.items():
            for k in sorted(ks, key=lambda k: -abs(k["hoehe"])):
                s = ds.sonden[k["sonde"]]
                w.writerow([s["kenn"], s["name"], var, datum(ds.tage[k["index"]]), f"{100 * np.expm1(k['hoehe']):.1f}"])
    namen = _abbildungen(aus, ds, erg_h, ev, sp_test, st_test, schnee, beispiel) if abbildungen else []
    (aus / "BERICHT.md").write_text(text(ergebnisse, namen), encoding="utf-8")
    return ergebnisse


def spanne(werte: list[float]) -> str:
    lo, hi = de(min(werte), 0, True), de(max(werte), 0, True)
    return lo if lo == hi else f"{lo} bis {hi}"


def text(r: dict, abb: list[str]) -> str:
    d, h, tg = r["daten"], r["stunden"], r["tage"]
    st = h["test"]
    zeilen = []
    for k, z in st["je_fehler"].items():
        art, g = k.split("|")
        name = {"spitze": "Spitze (1 Stunde)", "stufe": "Stufe nach oben", "drift": "Drift über 24 h",
                "absenkung": "Stufe nach unten", "haenger": "Hänger (12 gleiche Werte)"}[art]
        groesse = "–" if art == "haenger" else de(float(g), 0, True)
        zeilen.append(f"| {name} | {groesse} | {z['n']} | {de(z['trefferquote'], 0, True)} | "
                      f"{de(z['einordnung'], 0, True)} |")
    praez = [p["praezision"] for p in st["praezision"] if p["praezision"] is not None]
    sp = tg["test"]["je_stufe"]
    sprung_zeilen = [f"| {de(float(s), 1, True)} | {de(sp['roh'][s]['trefferquote'], 0, True)} | "
                     f"{de(sp['nachbarn'][s]['trefferquote'], 0, True)} |" for s in sp["roh"]]
    schnee_zeilen = [f"| {k} | {de(v['tage'], 0)} | {de(v.get('sonden'), 0)} | {de(v['median'], 1, True)} | "
                     f"{de(v['q25'], 1, True)} bis {de(v['q75'], 1, True)} |"
                     for k, v in tg["schnee"].items() if v["tage"]]
    e = h["ereignisse"]
    j = h["je_1000_stundenwerte"]
    lz = r["laufzeit_s"]
    bild = lambda n, t: f"\n![{t}](abbildungen/{n})\n" if n in abb else ""  # noqa: E731
    stunden_von = tdm(np.datetime64(d["stunden_von"]))
    stunden_bis = tdm(np.datetime64(d["stunden_bis"]))
    return f"""# Trend- und Plausibilitätsanalyse auf offenen ODL-Daten

**Bericht zu odlscan {r['version']}** · Panagiotis Herbe · ausgewertet {tdm(np.datetime64(r['ausgewertet'][:10]))}
(UTC), Rohablage `{r['rohablage']}`

## Auf einen Blick

- **Daten:** {de(d['sonden_in_betrieb'], 0)} ODL-Sonden des BfS in Betrieb, {de(d['tageswerte'], 0)} Tageswerte
  ({tdm(np.datetime64(d['tage_von']))} bis {tdm(np.datetime64(d['tage_bis']))}) und {de(d['stundenwerte'], 0)}
  Stundenwerte ({stunden_von} bis {stunden_bis}, UTC), dazu Niederschlag und Schneehöhe des DWD. Alles offen
  verfügbar, unverändert abgelegt und mit SHA-256 protokolliert.
- **Plausibilitätsprüfung (Stunden):** In echte Reihen eingebaute Fehler von 20 % der ODL (Spitze, Stufe,
  Absenkung) findet die Prüfung zu {spanne([st['je_fehler'][k]['trefferquote'] for k in ('spitze|0.2', 'stufe|0.2', 'absenkung|0.2')])},
  von 10 % zu {spanne([st['je_fehler'][k]['trefferquote'] for k in ('spitze|0.1', 'stufe|0.1', 'absenkung|0.1')])},
  Hänger zu {de(st['je_fehler']['haenger|0.0']['trefferquote'], 0, True)}; Präzision der Meldungen an den Prüfer
  {spanne(praez)}. Von den Erhöhungen an Sonden mit Regenmesser fallen
  {de(h['anteil_regen_an_erhoehungen_mit_messer'], 0, True)} mit Regen zusammen und werden als „Regen“ eingeordnet.
- **Voralarm-Regel nachgebildet:** {h['voralarme']} Ereignisse, in denen zwei Sonden unter 30 km Abstand
  innerhalb einer Stunde erhöht sind; bei {h['voralarme_regen_ueberwiegend']} davon regnet es an der Mehrheit der
  beteiligten Sonden.
- **Sprungstellen (Tage):** Bei gleichem Alarmbudget ({de(tg['alarm_anteil'], 0, True)} der Sonden mit
  Kandidat) findet der Vergleich gegen den Median der Nachbarsonden eine eingebaute Stufe von 10 % zu
  {de(sp['nachbarn']['0.1']['trefferquote'], 0, True)}, die Reihe allein zu {de(sp['roh']['0.1']['trefferquote'], 0, True)};
  Stufen von 5 % und weniger bleiben mit einem Jahr Tageswerten meist unentdeckt.
- **Schnee:** Bei 16–30 cm Schneehöhe liegt die Tages-ODL im Median um
  {de(-(tg['schnee'].get('16–30 cm', {}).get('median') or np.nan), 1, True)} unter den schneefreien Tagen derselben
  Sonde, bei mehr als 30 cm um {de(-(tg['schnee'].get('> 30 cm', {}).get('median') or np.nan), 1, True)}.

## 1 Ziel

Der Bericht zeigt an echten, öffentlich zugänglichen Messdaten des ODL-Messnetzes, wie eine automatische
Plausibilitätsprüfung und eine Trendanalyse aufgebaut, getestet und in Zahlen bewertet werden können. Er ist eine
kleine Vorstudie: Die öffentliche Schnittstelle liefert ein Jahr Tageswerte und sieben Tage Stundenwerte, nicht
die 28 Jahre und 10-Minuten-Werte der internen Datenbank.

## 2 Daten

| Quelle | Inhalt | Lizenz |
|---|---|---|
| BfS, WFS `https://www.imis.bfs.de/ogc/opendata/ows`, Layer `odlinfo_sitelist`, `odlinfo_timeseries_odl_24h`, `odlinfo_timeseries_odl_1h` | Messstellen, Tages- und Stundenwerte der Gamma-ODL (µSv/h) | Datenlizenz Deutschland – Namensnennung – 2.0 |
| DWD Open Data, `climate/hourly/precipitation/recent` | Stündlicher Niederschlag R1 (mm) | CC BY 4.0 |
| DWD Open Data, `climate/daily/more_precip/recent` | Tägliche Schneehöhe SH_TAG (cm) | CC BY 4.0 |

- {d['sonden_in_betrieb']} Sonden mit Status „in Betrieb“; Stundenwerte für {d['mit_stundenwerten']}, Tageswerte
  für {d['mit_tageswerten']}. Vollständigkeit: Stunden {de(d['vollstaendig_stunden'], 1, True)}, Tage
  {de(d['vollstaendig_tage'], 1, True)}.
- Median der Tageswerte je Sonde: {de(d['odl_median'], 3)} µSv/h (5–95 %: {de(d['odl_p5'], 3)} bis
  {de(d['odl_p95'], 3)} µSv/h; kleinster {de(d['odl_min'], 3)}, größter {de(d['odl_max'], 3)} µSv/h).
- DWD-Zuordnung: nächste Station mit Datei im Umkreis von 20 km. Stündlicher Niederschlag für
  {d['mit_regenmesser_stunde']} Sonden, Schneehöhe für {d['mit_schneemessung_tag']} Sonden.
- Seit 01.07.2025 rechnet das BfS die ODL mit geänderter Methode (laut BfS geringe Erhöhung); der ausgewertete
  Zeitraum liegt danach.
- Jede Antwort liegt unverändert unter `raw/<Abrufdatum>/`, mit URL, SHA-256 und Abrufzeit in `manifest.jsonl`;
  ausgewertet wird nur aus diesen Dateien.
{bild('abb1_karte.png', 'Karte der Sonden')}
## 3 Verfahren

**Stunden (Plausibilität und Voralarme, Bezug AP 3/4).** Basislinie je Sonde: Median der vorausgehenden 24
Stundenwerte (kausal, also im Betrieb so rechenbar). Streuung: 1,4826 × MAD der Abweichungen, mindestens
0,002 µSv/h. Markiert wird eine Erhöhung bei z ≥ 4 und mindestens 0,005 µSv/h, eine Absenkung spiegelbildlich, ein
Hänger bei sechs gleichen Werten in Folge. Eine Erhöhung heißt „regen“, wenn die nächste DWD-Station in t−2 … t+1
mindestens 0,1 mm meldet, „regional“, wenn eine Nachbarsonde (≤ 30 km) gleichzeitig z ≥ 3 zeigt, sonst „lokal“.
Die Voralarm-Regel des BfS (zwei Sonden unter 30 km innerhalb einer Stunde über Schwelle) ist mit z ≥ 4 statt der
nicht öffentlichen standortspezifischen Schwellen nachgebildet.

**Tage (Trends und Sprungstellen, Bezug AP 2).** Binäre Segmentierung des Mittelwerts von log(ODL),
Mindestsegment 21 Tage, Strafterm c · σ² · ln n (σ aus den Tagesdifferenzen). Echte Tagesreihen sind
autokorreliert; mit dem üblichen c = 3 hätten {de(tg['sonden_mit_sprung_bei_strafe_3']['roh'], 0)} von
{de(d['mit_tageswerten'], 0)} Sonden einen Sprung. c wird deshalb je Variante so kalibriert, dass
{de(tg['alarm_anteil'], 0, True)} der Sonden einen Kandidaten zeigen (Alarmbudget, Annahme): c =
{de(tg['strafe_kalibriert']['roh'], 1)} für die Reihe allein, {de(tg['strafe_kalibriert']['nachbarn'], 1)} gegen
Nachbarn. Variante „gegen Nachbarn“: log(ODL) der Sonde minus Median der
Nachbarn (≤ 50 km, Höhenunterschied ≤ 300 m, mindestens drei), wie beim Homogenisieren von Klimareihen gegen
Referenzreihen. Tage mit
Schneedecke werden ausgeblendet. Schnee-Effekt: Tageswert gegen den Median der schneefreien Tage derselben Sonde
im Fenster ± 15 Tage.

**Messung der Güte.** In echte Reihen werden künstliche Fehler eingebaut ({len(st['praezision'])} Durchläufe mit
festen Zufallsstartwerten, je bis zu {st['praezision'][0]['eingebaut']} Sonden; nur an trockenen, unauffälligen
Stellen) und wiedergefunden. Präzision: Anteil der Meldungen, die ein Prüfer ansehen müsste („lokal“, Absenkung,
Hänger) und die auf einen eingebauten Fehler fallen, mit dem echten Hintergrund aller übrigen Sonden.

## 4 Ergebnisse: Stundenwerte

{de(h['bewertete_stundenwerte'], 0)} bewertbare Stundenwerte (die ersten 24 Stunden je Sonde dienen der
Basislinie). Ereignisse auf den echten Daten:

| Klasse | Ereignisse | je 1.000 Stundenwerte |
|---|---|---|
| Erhöhung mit Regen | {e.get('regen', 0)} | {de(j.get('regen', 0), 2)} |
| Erhöhung, regional ohne Regen am Messer | {e.get('regional', 0)} | {de(j.get('regional', 0), 2)} |
| Erhöhung, lokal (technisch prüfen) | {e.get('lokal', 0)} | {de(j.get('lokal', 0), 2)} |
| Absenkung | {e.get('absenkung', 0)} | {de(j.get('absenkung', 0), 2)} |
| Hänger | {e.get('haenger', 0)} | {de(j.get('haenger', 0), 2)} |

Abklingen nach der Spitze (Median von (x(t+1) − b) / (x(t) − b)): Regen {de(h['abkling_median']['regen'], 2)}
(n = {h['abkling_n']['regen']}), regional {de(h['abkling_median']['regional'], 2)}
(n = {h['abkling_n']['regional']}), lokal {de(h['abkling_median']['lokal'], 2)} (n = {h['abkling_n']['lokal']}).
**Negativer Befund:** Mit Stundenwerten trennt das Abklingen Regen und lokale Ereignisse kaum. Die
Radon-Folgeprodukte (Halbwertszeiten 26,8 und 19,9 min) klingen innerhalb einer Stunde ab, Regen dauert aber oft
mehrere Stunden; für die Zerfallssignatur braucht es die 10-Minuten-Werte der BfS-Datenbank.
{bild('abb2_regen.png', 'Beispiel Regenereignis')}
**Eingebaute Fehler:**

| Fehler | Größe | eingebaut | erkannt | richtig eingeordnet |
|---|---|---|---|---|
{chr(10).join(zeilen)}

Präzision der Prüfer-Meldungen je Durchlauf: {', '.join(de(p, 0, True) for p in praez)} (eingebaut je Durchlauf
{st['praezision'][0]['eingebaut']} Fehler in {de(d['mit_stundenwerten'], 0)} Sonden über sieben Tage). Das ist eine Untergrenze:
Auch die „anderen“ Meldungen können echte Auffälligkeiten sein.
{bild('abb3_stundentest.png', 'Trefferquote Stundenwerte')}
**Voralarme (nachgebildet):** {h['voralarme']} Ereignisse in sieben Tagen, im Median
{de(h['voralarme_sonden_median'], 0)} Sonden je Ereignis; {h['voralarme_regen_ueberwiegend']} davon mit Regen an
der Mehrheit der beteiligten Sonden. Die übrigen {h['voralarme'] - h['voralarme_regen_ueberwiegend']} sind regional
(mehrere Sonden zugleich), aber der nächste Regenmesser meldet nichts: Kandidaten für Niederschlag, den eine
Punktmessung bis 20 km entfernt nicht sieht; Radardaten (DWD RADOLAN) würden das klären.

## 5 Ergebnisse: Tageswerte

Sprungkandidaten auf den echten Daten mit kalibriertem Strafterm: {tg['kandidaten_roh']} an
{tg['sonden_mit_kandidat_roh']} Sonden auf der Reihe allein, {tg['kandidaten_nachbarn']} an
{tg['sonden_mit_kandidat_nachbarn']} Sonden gegen Nachbarn ({de(tg['sonden_mit_referenz'], 0)} Sonden haben genug
Nachbarn; Liste in `sprungkandidaten.csv`). Kandidaten sind keine Befunde: Ob ein Sondenwechsel,
eine Standortänderung oder Bewuchs dahintersteht, zeigen erst die internen Stammdaten.

**Eingebaute Stufen ({de(tg['test']['sonden'], 0)} geeignete Sonden, beide Varianten mit gleichem Alarmbudget):**

| Stufe | erkannt, Reihe allein | erkannt, gegen Nachbarn |
|---|---|---|
{chr(10).join(sprung_zeilen)}
{bild('abb4_spruenge.png', 'Sprungerkennung')}
**Schnee:**

| Schneehöhe | Tage | Sonden | Median Abweichung | mittlere Hälfte |
|---|---|---|---|---|
{chr(10).join(schnee_zeilen)}
{bild('abb5_schnee.png', 'Schnee-Effekt')}
## 6 Grenzen

- Ein Jahr Tageswerte erlaubt keine Aussage zu langfristigen Trends; gezeigt ist, wie groß eine Änderung sein muss,
  um gefunden zu werden, und dass der Nachbarvergleich diese Schwelle senkt.
- Das Alarmbudget von {de(tg['alarm_anteil'], 0, True)} der Sonden je Jahr ist eine Annahme; die Zahl echter
  Sondenwechsel und Standortänderungen steht in den Stammdaten des BfS.
- Sieben Tage Stundenwerte sind eine Stichprobe einer Herbstwoche; Gewitterlagen, Schnee und Inversionen sind
  darin nicht oder kaum enthalten.
- Die echten Plausibilisierungsentscheidungen des BfS sind nicht öffentlich. Die Trefferquoten gelten für
  eingebaute Fehler, nicht für die realen Fehlerbilder; die Präzision ist eine Untergrenze.
- Der Regenmesser steht bis zu 20 km von der Sonde entfernt; lokale Schauer verfehlt er. Die DWD-Daten der Reihe
  `recent` sind nur eingeschränkt geprüft.

## 7 Reproduzieren

```
pip install .[plots]
odlscan holen --daten daten
odlscan auswerten --raw daten/raw/<Abrufdatum> --aus nachweis/<Datum>
```

Laufzeiten dieses Laufs: Einlesen {de(lz['einlesen_s'], 0)} s, Stundenprüfung {de(lz['stunden_pruefung_s'], 1)} s,
Stundentest {de(lz['stunden_test_s'], 1)} s, Tagesprüfung {de(lz['tage_pruefung_s'], 1)} s, Tagestest
{de(lz['tage_test_s'], 1)} s; Python {r['umgebung']['python']}, NumPy {r['umgebung']['numpy']}, {r['umgebung']['system']}.

Datenquellen: Bundesamt für Strahlenschutz (BfS), ODL-Messnetz, Datenlizenz Deutschland – Namensnennung – 2.0;
Deutscher Wetterdienst (DWD), Open Data, CC BY 4.0.
"""
