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


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95-%-Vertrauensbereich einer Trefferquote k/n nach Wilson."""
    if not n:
        return np.nan, np.nan
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


FARBE = "#0b5866"  # Petrol
GRAU = "#8a979c"
REGEN = "#7fb3d5"
NAMEN = {"spitze": "Spitze 1 h", "stufe": "Stufe nach oben", "drift": "Drift über 24 h", "absenkung": "Stufe nach unten",
         "haenger": "Hänger (12 gleiche Werte)"}


def _abbildungen(aus: Path, ds, erg_h, ev, sp_test, st_test, schnee, beispiel) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.formatter.use_locale": False})
    abb = aus / "abbildungen"
    abb.mkdir(parents=True, exist_ok=True)
    namen = []
    dpi = 300

    def deutsch(ax, achse="y"):
        """Teilstriche mit Dezimalkomma, Nachkommastellen nach dem Teilstrich-Abstand."""
        a = ax.yaxis if achse == "y" else ax.xaxis
        ticks = a.get_majorticklocs()
        schritt = float(np.min(np.diff(ticks))) if len(ticks) > 1 else 1.0
        stellen = max(0, -int(np.floor(np.log10(schritt))))
        a.set_major_locator(mticker.FixedLocator(ticks))
        a.set_major_formatter(mticker.FixedFormatter([de(float(t), stellen) for t in ticks]))

    # 1 Karte der Sonden, Farbe = Median der Tageswerte; Farbskala begrenzt (Pfeile an der Skala)
    med = np.nanmedian(ds.odl_d, axis=1)
    lo, hi = np.nanpercentile(med, 2), np.nanpercentile(med, 98)
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    sc = ax.scatter(ds.lon, ds.lat, c=med, s=5, cmap="viridis", vmin=lo, vmax=hi, linewidths=0)
    ax.set_aspect(1 / np.cos(np.radians(51)))
    ax.set_xlabel("Länge (°)")
    ax.set_ylabel("Breite (°)")
    ax.set_title(f"{de(int(np.isfinite(med).sum()), 0)} ODL-Sonden: Median der Tageswerte", fontsize=9.5)
    cb = fig.colorbar(sc, ax=ax, shrink=0.8, extend="both", fraction=0.05, pad=0.02)
    cb.set_label("µSv/h (Skala 2.–98. Perzentil)")
    cb.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: de(v, 3)))
    fig.tight_layout()
    fig.savefig(abb / "abb1_karte.png", dpi=dpi)
    plt.close(fig)
    namen.append("abb1_karte.png")

    # 2 Beispiel Regenereignis; rechte Achse sichtbar, damit Teilstriche nicht wie Minuszeichen aussehen
    if beispiel is not None:
        i, t = beispiel
        a, b = max(0, t - 36), min(ds.odl_h.shape[1], t + 24)
        x = ds.odl_h[i, a:b]
        e = erg_h[i]
        zeit = ds.stunden[a:b].astype("datetime64[h]").astype("datetime64[s]").astype(object)
        fig, ax = plt.subplots(figsize=(7, 3.3))
        ax2 = ax.twinx()
        ax2.bar(zeit, ds.regen_h[i, a:b], width=1 / 24, color=REGEN, alpha=0.8, label="Niederschlag DWD (mm/h)")
        ax2.set_ylabel("Niederschlag (mm/h)")
        ax2.spines["right"].set_visible(True)
        ax2.set_ylim(0, max(1.0, float(np.nanmax(ds.regen_h[i, a:b])) * 1.15))
        deutsch(ax2)
        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)
        ax.plot(zeit, x, color=FARBE, lw=1.5, label="ODL (Stundenwert)")
        ax.plot(zeit, e["b"][a:b], color=GRAU, lw=1, ls="--", label="Basislinie (Median 24 h)")
        ax.plot(zeit, e["b"][a:b] + anomalie.Z_SCHWELLE * e["s"], color="#b03a2e", lw=0.9, ls=":",
                label="Schwelle z = 4")
        markiert = e["oben"][a:b]
        ax.scatter(np.array(zeit)[markiert], x[markiert], s=14, color="#b03a2e", zorder=3, label="als Erhöhung markiert")
        ax.set_ylabel("ODL (µSv/h)")
        deutsch(ax)
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.\n%H Uhr"))
        s = ds.sonden[i]
        ax.set_title(f"Sonde {s['name']} ({s['kenn']}): Erhöhung mit Regen", fontsize=9.5)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left", frameon=False)
        ax.set_xlabel("Zeit (UTC, Ende der Messstunde)")
        fig.tight_layout()
        fig.savefig(abb / "abb2_regen.png", dpi=dpi)
        plt.close(fig)
        namen.append("abb2_regen.png")

    # 3 Trefferquote Stunden: waagrechte Balken mit 95-%-Vertrauensbereich und Fallzahl
    eintraege = []
    for k, z in st_test["je_fehler"].items():
        art, g = k.split("|")
        name = NAMEN[art] if art == "haenger" else f"{NAMEN[art]}, {de(float(g), 0, True)}"
        lo_, hi_ = wilson(z["erkannt"], z["n"])
        eintraege.append((f"{name} (n = {z['n']})", 100 * (z["trefferquote"] or 0), 100 * lo_, 100 * hi_, art))
    fig, ax = plt.subplots(figsize=(7, 4.6))
    y = np.arange(len(eintraege))[::-1]
    werte = np.array([w for _, w, _, _, _ in eintraege])
    fehler = np.clip(np.array([[w - l, h - w] for _, w, l, h, _ in eintraege]).T, 0, None)  # 0/100 %: Rundung
    farben = [GRAU if art == "drift" else FARBE for *_, art in eintraege]
    ax.barh(y, werte, color=farben, height=0.62)
    ax.errorbar(werte, y, xerr=fehler, fmt="none", ecolor="#1c2529", elinewidth=0.8, capsize=2.5)
    for yy, (_, w, _, h, _) in zip(y, eintraege):
        ax.text(h + 1.5, yy, de(w / 100, 0, True), va="center", fontsize=7.5)
    ax.set_yticks(y, [n for n, *_ in eintraege], fontsize=8)
    ax.set_xlim(0, 112)
    ax.set_xlabel("Trefferquote (%), Fehlerbalken: 95-%-Vertrauensbereich (Wilson)")
    ax.set_title("Stundenwerte: eingebaute Fehler, die die Prüfung meldet (Drift grau)", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(abb / "abb3_stundentest.png", dpi=dpi)
    plt.close(fig)
    namen.append("abb3_stundentest.png")

    # 4 Sprungerkennung: drei Varianten mit Vertrauensbereich
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    varianten = (("roh", GRAU, "o", "-", "Reihe allein"), ("nachbarn", FARBE, "o", "-", "gegen Nachbarn (Median ≤ 50 km)"),
                 ("korrelation", "#c27c0e", "s", "--", "Korrelations-Nachbarn (verworfen)"))
    versatz = {"roh": 0.97, "nachbarn": 1.0, "korrelation": 1.03}
    for var, farbe, mk, ls, name in varianten:
        if var not in sp_test["je_stufe"]:
            continue
        zs = sp_test["je_stufe"][var]
        xs = np.array([100 * float(s) for s in zs]) * versatz[var]
        ys = np.array([100 * (z["trefferquote"] or 0) for z in zs.values()])
        ci = np.array([wilson(z["erkannt"], z["n"]) for z in zs.values()]) * 100
        ax.errorbar(xs, ys, yerr=np.clip([ys - ci[:, 0], ci[:, 1] - ys], 0, None), color=farbe, marker=mk, ms=4,
                    ls=ls, lw=1.3,
                    capsize=2.5, elinewidth=0.8, label=name)
    ax.axhline(80, color="#b03a2e", lw=0.7, ls=":")
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1, 2, 3, 5, 10], ["0,5", "1", "2", "3", "5", "10"])
    ax.minorticks_off()
    ax.set_xlabel("eingebaute Stufe (% der ODL)")
    ax.set_ylabel("Trefferquote (%)")
    ax.set_ylim(0, 105)
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    ax.set_title("Tageswerte: eingebaute Stufen bei gleichem Alarmbudget", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(abb / "abb4_spruenge.png", dpi=dpi)
    plt.close(fig)
    namen.append("abb4_spruenge.png")

    # 5 Schnee: Zusammenhang, keine Ursachenbehauptung; Fallzahlen an der Achse
    klassen = [k for k in schnee if k != "schneefrei" and schnee[k]["tage"] > 0]
    if klassen:
        fig, ax = plt.subplots(figsize=(6.6, 3.4))
        daten = [100 * schnee["schneefrei"]["werte"]] + [100 * schnee[k]["werte"] for k in klassen]
        ax.boxplot(daten, showfliers=False, widths=0.55, medianprops={"color": FARBE, "lw": 1.6},
                   boxprops={"color": "#1c2529"}, whiskerprops={"color": "#1c2529"}, capprops={"color": "#1c2529"})
        etiketten = [f"schneefrei\n{de(schnee['schneefrei']['tage'], 0)} Stichproben\n(jeder 7. Tag)"] + [
            f"{k}\n{de(schnee[k]['tage'], 0)} Sonden-Tage\n{de(schnee[k]['sonden'], 0)} Sonden" for k in klassen]
        ax.set_xticks(range(1, len(daten) + 1), etiketten, fontsize=7.5)
        ax.axhline(0, color=GRAU, lw=0.7)
        ax.set_ylabel("Abweichung der Tages-ODL (%)")
        ax.set_xlabel("Schneehöhe an der nächsten DWD-Station")
        ax.set_title("Tages-ODL an Schneetagen gegenüber schneefreien Tagen derselben Sonde (± 15 Tage)", fontsize=9)
        fig.tight_layout()
        fig.savefig(abb / "abb5_schnee.png", dpi=dpi)
        plt.close(fig)
        namen.append("abb5_schnee.png")
    return namen


def abruf_statistik(raw: Path) -> dict:
    """Abrufe laut manifest.jsonl (ohne lokal berechnete Dateien), Bytes wie geliefert und Größe der Ablage."""
    m = raw / "manifest.jsonl"
    if not m.exists():
        return {}
    saetze = [json.loads(z) for z in m.read_text(encoding="utf-8").splitlines() if z.strip()]
    abrufe = [x for x in saetze if x["url"].startswith("http")]
    platte = sum(f.stat().st_size for f in raw.rglob("*") if f.is_file() and f.name != "manifest.jsonl")
    return {"eintraege": len(saetze), "abrufe": len(abrufe),
            "abrufe_bfs": sum("bfs.de" in x["url"] for x in abrufe),
            "abrufe_dwd": sum("dwd.de" in x["url"] for x in abrufe),
            "mb_wie_geliefert": sum(x["bytes"] for x in abrufe) / 1e6, "mb_ablage": platte / 1e6}


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
    for v in va:
        v["klasse"] = anomalie.voralarm_klasse(v)
    uhr["stunden_pruefung_s"] = time.perf_counter() - t
    t = time.perf_counter()
    st_test = bewertung.stunden_test(ds.odl_h, erg_h, ds.regen_h, nb30, durchlaeufe, je_lauf)
    uhr["stunden_test_s"] = time.perf_counter() - t
    bewertet = int(sum(np.isfinite(e["z"]).sum() for e in erg_h))

    zaehl, mit_messer = {}, {}
    for v in ev:
        zaehl[v["klasse"]] = zaehl.get(v["klasse"], 0) + 1
        mit_messer[v["klasse"]] = mit_messer.get(v["klasse"], 0) + int(v["messer"])
    regen_stunden = np.flatnonzero(np.isfinite(ds.regen_h).any(axis=0))
    letzte_regenstunde = str(ds.stunden[regen_stunden[-1]]) if len(regen_stunden) else None
    ohne_messer_tage = {}
    for v in ev:
        if v["art"] == "oben" and not v["messer"]:
            tag = datum(ds.stunden[v["spitze"]])
            ohne_messer_tage[tag] = ohne_messer_tage.get(tag, 0) + 1
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
    # Vergleichsvariante: Referenz aus den am stärksten korrelierten Nachbarn (verworfen, aber gemessen)
    ref_k = trend.referenz_korrelation(logodl, geo.nachbarn(ds.lat, ds.lon, trend.KORR_KM))
    strafe_k = trend.kalibrieren([trend.reihe(logodl[i], ref_k[i], ds.schnee_d[i]) for i in range(n)])
    kandidaten = {"roh": [], "nachbarn": []}
    for var, rs in reihen.items():
        for i, y in enumerate(rs):
            for p in trend.spruenge(y, strafe=strafe[var]):
                kandidaten[var].append({"sonde": i, **p})
    schnee = trend.schnee_effekt(ds.odl_d, ds.schnee_d)
    uhr["tage_pruefung_s"] = time.perf_counter() - t
    t = time.perf_counter()
    sp_test = bewertung.tages_test(logodl, ref, ds.schnee_d, {**strafe, "korrelation": strafe_k}, durchlaeufe,
                                   je_lauf, ref_korrelation=ref_k)
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

    abruf = abruf_statistik(raw)
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
            "letzte_stunde_mit_regenmesser": letzte_regenstunde,
            "abruf": abruf,
        },
        "stunden": {
            "bewertete_stundenwerte": bewertet,
            "ereignisse": zaehl,
            "ereignisse_mit_messer": mit_messer,
            "erhoehungen_ohne_messer_je_tag": dict(sorted(ohne_messer_tage.items())),
            "je_1000_stundenwerte": {k: 1000 * v / bewertet for k, v in zaehl.items()},
            "erhoehungen_mit_regenmesser": len(oben_messer),
            "anteil_regen_an_erhoehungen_mit_messer": (sum(v["klasse"] == "regen" for v in oben_messer)
                                                       / len(oben_messer)) if oben_messer else None,
            "abkling_median": {k: float(np.median(v)) if v else None for k, v in abkling.items()},
            "abkling_n": {k: len(v) for k, v in abkling.items()},
            "voralarme": len(va),
            "voralarme_regen_ueberwiegend": sum(v["regen_anteil"] >= 0.5 for v in va),
            "voralarme_klassen": {k: sum(v["klasse"] == k for v in va) for k in ("regen", "trocken", "gemischt", "ohne_messer")},
            "voralarme_sonden_median": float(np.median([v["sonden"] for v in va])) if va else None,
            "test": st_test,
        },
        "tage": {
            "kandidaten_roh": len(kandidaten["roh"]),
            "kandidaten_nachbarn": len(kandidaten["nachbarn"]),
            "sonden_mit_kandidat_roh": len({k["sonde"] for k in kandidaten["roh"]}),
            "sonden_mit_kandidat_nachbarn": len({k["sonde"] for k in kandidaten["nachbarn"]}),
            "sonden_mit_referenz": int(np.isfinite(ref).any(axis=1).sum()),
            "sonden_mit_korrelationsreferenz": int(np.isfinite(ref_k).any(axis=1).sum()),
            "alarm_anteil": trend.ALARM_ANTEIL, "strafe_kalibriert": {**strafe, "korrelation": strafe_k},
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
    with open(aus / "voralarme_stunden.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["von_utc", "bis_utc", "sonden", "knoten", "anteil_regen", "anteil_mit_messer",
                    "anteil_trocken", "klasse"])
        for v in va:
            w.writerow([ds.stunden[v["von"]], ds.stunden[v["bis"]], v["sonden"], v["knoten"],
                        f"{v['regen_anteil']:.2f}", f"{v['messer_anteil']:.2f}", f"{v['trocken_anteil']:.2f}",
                        v["klasse"]])
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


def utc(stunde: str | None) -> str:
    """'2026-11-02T01' -> '02.11.2026, 01 UTC'."""
    if not stunde:
        return "–"
    return f"{tdm(np.datetime64(stunde[:10]))}, {stunde[11:13]} UTC"


def text(r: dict, abb: list[str]) -> str:
    d, h, tg = r["daten"], r["stunden"], r["tage"]
    st = h["test"]
    jf = st["je_fehler"]
    tq = lambda k: de(jf[k]["trefferquote"], 0, True)  # noqa: E731
    zeilen = []
    for k, z in jf.items():
        art, g = k.split("|")
        name = {"spitze": "Spitze (1 Stunde)", "stufe": "Stufe nach oben", "drift": "Drift über 24 h",
                "absenkung": "Stufe nach unten", "haenger": "Hänger (12 gleiche Werte)"}[art]
        groesse = "–" if art == "haenger" else de(float(g), 0, True)
        lo, hi = wilson(z["erkannt"], z["n"])
        zeilen.append(f"| {name} | {groesse} | {z['n']} | {de(z['trefferquote'], 0, True)} | "
                      f"{de(lo, 0, True)} bis {de(hi, 0, True)} | {de(z['einordnung'], 0, True)} |")
    praez = [p["praezision"] for p in st["praezision"] if p["praezision"] is not None]
    sp = tg["test"]["je_stufe"]
    hat_k = "korrelation" in sp
    kopf_k = " | erkannt, Korrelations-Nachbarn" if hat_k else ""
    trenn_k = "|---" if hat_k else ""
    sprung_zeilen = [f"| {de(float(s), 1, True)} | {sp['nachbarn'][s]['n']} | {de(sp['roh'][s]['trefferquote'], 0, True)} | "
                     f"{de(sp['nachbarn'][s]['trefferquote'], 0, True)}"
                     + (f" | {de(sp['korrelation'][s]['trefferquote'], 0, True)}"
                        + ("" if sp['korrelation'][s]['n'] == sp['nachbarn'][s]['n'] else f" (n = {sp['korrelation'][s]['n']})")
                        if hat_k else "") + " |" for s in sp["roh"]]
    schnee_zeilen = [f"| {k} | {de(v['tage'], 0)} | {de(v.get('sonden'), 0)} | {de(v['median'], 1, True)} | "
                     f"{de(v['q25'], 1, True)} bis {de(v['q75'], 1, True)} |"
                     for k, v in tg["schnee"].items() if v["tage"] and k != "schneefrei"]
    frei = tg["schnee"]["schneefrei"]
    e = h["ereignisse"]
    mm = h.get("ereignisse_mit_messer", {})
    j = h["je_1000_stundenwerte"]
    vk = h.get("voralarme_klassen", {})
    lz = r["laufzeit_s"]
    ab = d.get("abruf", {})
    nr = {n: i + 1 for i, n in enumerate(abb)}
    # Bild und Unterschrift in einem Absatz, damit sie beim Drucken nicht auf zwei Seiten getrennt werden
    bild = lambda n, t, u: (f"\n![Abb. {nr[n]}: {t}](abbildungen/{n})\n*Abb. {nr[n]}: {u}*\n"  # noqa: E731
                            if n in abb else "")
    abb_nr = lambda n: f"Abb. {nr[n]}" if n in nr else "die Abbildung"  # noqa: E731
    stunden_von = tdm(np.datetime64(d["stunden_von"]))
    stunden_bis = tdm(np.datetime64(d["stunden_bis"]))
    regional_ohne = e.get("regional", 0) - mm.get("regional", 0)
    lokal_ohne = e.get("lokal", 0) - mm.get("lokal", 0)
    ohne_tage = h.get("erhoehungen_ohne_messer_je_tag", {})
    letzter_tag = d["stunden_bis"][:10]
    ohne_letzter = ohne_tage.get(letzter_tag, 0)
    schnee30 = tg["schnee"].get("> 30 cm", {})
    schnee16 = tg["schnee"].get("16–30 cm", {})
    nicht_regen = h["voralarme"] - vk.get("regen", h["voralarme_regen_ueberwiegend"])
    gemischt_satz = f", {vk['gemischt']} teils nass, teils trocken" if vk.get("gemischt") else ""
    k10 = de(sp["korrelation"]["0.1"]["trefferquote"], 0, True) if hat_k else "–"
    k5 = de(sp["korrelation"]["0.05"]["trefferquote"], 0, True) if hat_k else "–"
    abruf_satz = (f"{de(ab['abrufe'], 0)} Abrufe ({de(ab['abrufe_bfs'], 0)} beim BfS, {de(ab['abrufe_dwd'], 0)} beim "
                  f"DWD), {de(ab['mb_wie_geliefert'], 0)} MB wie geliefert, {de(ab['mb_ablage'], 0)} MB in der Ablage "
                  f"(JSON gzip-komprimiert, ZIP wie geliefert); {de(ab['eintraege'], 0)} Einträge im Manifest mit "
                  f"den lokal berechneten Zuordnungsdateien" if ab else "Abrufzahlen: Manifest fehlt")
    return f"""# Trend- und Plausibilitätsanalyse auf offenen ODL-Daten

**Bericht zu odlscan {r['version']}** · Panagiotis Herbe · ausgewertet {tdm(np.datetime64(r['ausgewertet'][:10]))}
(UTC), Rohablage `{r['rohablage']}` · ersetzt den Bericht vom 02.11.2026 (odlscan 0.1.0); die Korrekturen stehen in
Abschnitt 8.

## Auf einen Blick

- **Daten:** {de(d['sonden_in_betrieb'], 0)} ODL-Sonden des BfS in Betrieb, {de(d['tageswerte'], 0)} Tageswerte
  ({tdm(np.datetime64(d['tage_von']))} bis {tdm(np.datetime64(d['tage_bis']))}) und {de(d['stundenwerte'], 0)}
  Stundenwerte ({stunden_von} bis {stunden_bis}, UTC), dazu Niederschlag und Schneehöhe des DWD. Alles offen
  verfügbar, unverändert abgelegt und mit SHA-256 protokolliert.
- **Plausibilitätsprüfung (Stunden):** Die einfache Prüfung (Median der letzten 24 Stunden als Basislinie, robuster
  z-Wert ≥ 4) findet in echte Reihen eingebaute Spitzen, Stufen und Absenkungen von 20 % der ODL zu
  {spanne([jf[k]['trefferquote'] for k in ('spitze|0.2', 'stufe|0.2', 'absenkung|0.2')])}, von 10 % zu
  {spanne([jf[k]['trefferquote'] for k in ('spitze|0.1', 'stufe|0.1', 'absenkung|0.1')])}. Eine Drift über
  24 Stunden findet sie schlecht: von 20 % zu {tq('drift|0.2')}, von 10 % zu {tq('drift|0.1')}. Hänger zu
  {tq('haenger|0.0')}. Präzision der Meldungen an den Prüfer {spanne(praez)}. Von den
  {h['erhoehungen_mit_regenmesser']} Erhöhungen, für die der nächste Regenmesser Werte hat, fallen
  {e.get('regen', 0)} ({de(h['anteil_regen_an_erhoehungen_mit_messer'], 0, True)}) mit Regen zusammen.
- **Voralarm-Regel nachgebildet:** {h['voralarme']} Ereignisse, in denen zwei Sonden unter 30 km Abstand
  innerhalb einer Stunde erhöht sind; bei {vk.get('regen', 0)} regnet es an der Mehrheit der beteiligten Sonden, bei
  {vk.get('ohne_messer', 0)} fehlen an der Mehrheit Regenmesserdaten, {vk.get('trocken', 0)} sind gemessen
  trocken{gemischt_satz}.
- **Sprungstellen (Tage):** Bei gleichem Alarmbudget ({de(tg['alarm_anteil'], 0, True)} der Sonden mit
  Kandidat) findet der Vergleich gegen den Median der Nachbarsonden eine eingebaute Stufe von 10 % zu
  {de(sp['nachbarn']['0.1']['trefferquote'], 0, True)}, die Reihe allein zu {de(sp['roh']['0.1']['trefferquote'], 0, True)};
  Stufen von 5 % und weniger bleiben mit einem Jahr Tageswerten meist unentdeckt.
- **Schnee:** Bei 16–30 cm Schneehöhe liegt die Tages-ODL im Median um
  {de(-(schnee16.get('median') or np.nan), 1, True)} unter den schneefreien Tagen derselben Sonde
  ({de(schnee16.get('tage'), 0)} Sonden-Tage an {de(schnee16.get('sonden'), 0)} Sonden), bei mehr als 30 cm um
  {de(-(schnee30.get('median') or np.nan), 1, True)} ({de(schnee30.get('tage'), 0)} Sonden-Tage an
  {de(schnee30.get('sonden'), 0)} Sonden).

## 1 Ziel

Der Bericht zeigt an echten, öffentlich zugänglichen Messdaten des ODL-Messnetzes, wie eine automatische
Plausibilitätsprüfung und eine Trendanalyse aufgebaut, getestet und in Zahlen bewertet werden können. Er ist eine
kleine Vorstudie: Die öffentliche Schnittstelle liefert ein Jahr Tageswerte und sieben Tage Stundenwerte, nicht
die vollständige Messhistorie.

## 2 Daten

| Quelle | Inhalt | Lizenz |
|---|---|---|
| BfS, WFS `https://www.imis.bfs.de/ogc/opendata/ows`, Layer `odlinfo_sitelist`, `odlinfo_timeseries_odl_24h`, `odlinfo_timeseries_odl_1h` | Messstellen, Tages- und Stundenwerte der Gamma-ODL (µSv/h) | Datenlizenz Deutschland – Namensnennung – 2.0 |
| DWD Open Data, `climate/hourly/precipitation/recent` | Stündlicher Niederschlag R1 (mm) | CC BY 4.0 |
| DWD Open Data, `climate/daily/more_precip/recent` | Tägliche Schneehöhe SH_TAG (cm) | CC BY 4.0 |

- {de(d['sonden_in_betrieb'], 0)} Sonden mit Status „in Betrieb“; Stundenwerte für {de(d['mit_stundenwerten'], 0)},
  Tageswerte für {de(d['mit_tageswerten'], 0)}. Vollständigkeit: Stunden {de(d['vollstaendig_stunden'], 1, True)}, Tage
  {de(d['vollstaendig_tage'], 1, True)}.
- Median der Tageswerte je Sonde: {de(d['odl_median'], 3)} µSv/h (5–95 %: {de(d['odl_p5'], 3)} bis
  {de(d['odl_p95'], 3)} µSv/h; kleinster {de(d['odl_min'], 3)}, größter {de(d['odl_max'], 3)} µSv/h).
- DWD-Zuordnung: nächste Station mit Datei im Umkreis von 20 km. Stündlicher Niederschlag für
  {de(d['mit_regenmesser_stunde'], 0)} Sonden, Schneehöhe für {de(d['mit_schneemessung_tag'], 0)} Sonden. Die stündliche
  DWD-Reihe endet in dieser Rohablage mit der Stunde {utc(d.get('letzte_stunde_mit_regenmesser'))}, die
  ODL-Stundenwerte mit {utc(d['stunden_bis'])}; für die Stunden dazwischen gibt es keine Messerdaten.
- Seit 01.07.2025 verwendet das BfS bei der Berechnung der ODL einen für den Notfallschutz optimierten
  Kalibrierfaktor; die berechneten Werte liegen nach Angabe des BfS seither etwa 14–25 % höher, je nach Gegend um bis
  zu etwa 0,025 µSv/h (ODL-INFO, „Berechnung der ODL-Messwerte“, gelesen 03.11.2026). Beide ausgewerteten Zeiträume
  liegen danach.
- Abruf: {abruf_satz}. Jede Antwort liegt unverändert unter `raw/<Abrufdatum>/`, mit URL, SHA-256 und Abrufzeit in
  `manifest.jsonl`; ausgewertet wird nur aus diesen Dateien.
{bild('abb1_karte.png', 'Karte der Sonden', f"Lage der {de(d['sonden_in_betrieb'], 0)} Sonden, Farbe = Median der Tageswerte je Sonde. Die Farbskala ist auf das 2. bis 98. Perzentil begrenzt; Sonden darunter oder darüber tragen die Endfarbe (Spitzen an der Skala). Was daraus folgt: Das Niveau unterscheidet sich zwischen den Sonden um mehr als den Faktor 4 ({de(d['odl_min'], 3)} bis {de(d['odl_max'], 3)} µSv/h); jede Prüfung arbeitet deshalb relativ zur eigenen Basislinie der Sonde.")}
## 3 Verfahren

**Stunden (Plausibilität und Voralarme).** Basislinie je Sonde: Median der vorausgehenden 24
Stundenwerte (kausal, also im Betrieb so rechenbar). Streuung: 1,4826 × MAD der Abweichungen, mindestens
0,002 µSv/h. Markiert wird eine Erhöhung bei z ≥ 4 und mindestens 0,005 µSv/h, eine Absenkung spiegelbildlich, ein
Hänger bei sechs gleichen Werten in Folge. Eine Erhöhung heißt „regen“, wenn die nächste DWD-Station in t−2 … t+1
mindestens 0,1 mm meldet, „regional“, wenn eine Nachbarsonde (≤ 30 km) gleichzeitig z ≥ 3 zeigt, sonst „lokal“.
Mitgeschrieben wird, ob der Regenmesser im Fenster überhaupt Werte hat: Ohne Messerdaten heißt „kein Regen
gemeldet“ nicht „trocken“. Die Voralarm-Regel des BfS (zwei Sonden unter 30 km innerhalb einer Stunde über
Schwelle) ist mit z ≥ 4 statt der nicht öffentlichen standortspezifischen Schwellen nachgebildet; je Voralarm wird
gezählt, an wie vielen der beteiligten Sonden und Stunden es regnet, der Messer Werte hat oder trocken meldet.

**Tage (Trends und Sprungstellen).** Binäre Segmentierung des Mittelwerts von log(ODL),
Mindestsegment 21 Tage, Strafterm c · σ² · ln n (σ aus den Tagesdifferenzen). Echte Tagesreihen sind
autokorreliert; mit dem üblichen c = 3 hätten {de(tg['sonden_mit_sprung_bei_strafe_3']['roh'], 0)} von
{de(d['mit_tageswerten'], 0)} Sonden einen Sprung. c wird deshalb je Variante so kalibriert, dass
{de(tg['alarm_anteil'], 0, True)} der Sonden einen Kandidaten zeigen (Alarmbudget, Annahme): c =
{de(tg['strafe_kalibriert']['roh'], 1)} für die Reihe allein, {de(tg['strafe_kalibriert']['nachbarn'], 1)} gegen
Nachbarn. Variante „gegen Nachbarn“: log(ODL) der Sonde minus Median der Nachbarn (≤ 50 km, Höhenunterschied
≤ 300 m, mindestens drei), wie beim Homogenisieren von Klimareihen gegen Referenzreihen. Vergleichsvariante
„Korrelations-Nachbarn“: Referenz aus den fünf Sonden im Umkreis von 75 km, deren Tagesänderungen am stärksten mit
denen der Sonde korrelieren (mindestens 200 gemeinsame Tage; {de(tg.get('sonden_mit_korrelationsreferenz'), 0)}
Sonden), Strafterm auf dasselbe Alarmbudget kalibriert. Tage mit Schneedecke werden ausgeblendet. Schnee-Effekt:
Tageswert gegen den Median der schneefreien Tage derselben Sonde im Fenster ± 15 Tage.

**Messung der Güte.** In echte Reihen werden künstliche Fehler eingebaut ({len(st['praezision'])} Durchläufe mit
festen Zufallsstartwerten, je bis zu {st['praezision'][0]['eingebaut']} Sonden; nur an trockenen, unauffälligen
Stellen mit Regenmesserdaten) und wiedergefunden. Präzision: Anteil der Meldungen, die ein Prüfer ansehen müsste
(„lokal“, Absenkung, Hänger) und die auf einen eingebauten Fehler fallen, mit dem echten Hintergrund aller übrigen
Sonden. Trefferquoten mit 95-%-Vertrauensbereich nach Wilson.

## 4 Ergebnisse: Stundenwerte

{de(h['bewertete_stundenwerte'], 0)} bewertbare Stundenwerte (die ersten 24 Stunden je Sonde dienen der
Basislinie). Ereignisse auf den echten Daten:

| Klasse | Ereignisse | davon mit Regenmesserdaten | je 1.000 Stundenwerte |
|---|---|---|---|
| Erhöhung mit Regen | {e.get('regen', 0)} | {mm.get('regen', 0)} | {de(j.get('regen', 0), 2)} |
| Erhöhung, regional (kein Regen gemeldet) | {e.get('regional', 0)} | {mm.get('regional', 0)} | {de(j.get('regional', 0), 2)} |
| Erhöhung, lokal (technisch prüfen) | {e.get('lokal', 0)} | {mm.get('lokal', 0)} | {de(j.get('lokal', 0), 2)} |
| Absenkung | {e.get('absenkung', 0)} | – | {de(j.get('absenkung', 0), 2)} |
| Hänger | {e.get('haenger', 0)} | – | {de(j.get('haenger', 0), 2)} |

Bei {regional_ohne} der {e.get('regional', 0)} regionalen und {lokal_ohne} der {e.get('lokal', 0)} lokalen
Erhöhungen hat der nächste Regenmesser im Fenster keine Werte, {ohne_letzter} davon am
{tdm(np.datetime64(letzter_tag))} nach dem Ende der DWD-Stundenreihe. Für diese Ereignisse ist Regen weder belegt
noch ausgeschlossen. Wo der Messer Werte hat, fallen {e.get('regen', 0)} von {h['erhoehungen_mit_regenmesser']}
Erhöhungen ({de(h['anteil_regen_an_erhoehungen_mit_messer'], 0, True)}) mit Regen zusammen.

Abklingen nach der Spitze (Median von (x(t+1) − b) / (x(t) − b)): Regen {de(h['abkling_median']['regen'], 2)}
(n = {h['abkling_n']['regen']}), regional {de(h['abkling_median']['regional'], 2)}
(n = {h['abkling_n']['regional']}), lokal {de(h['abkling_median']['lokal'], 2)} (n = {h['abkling_n']['lokal']}).
**Negativer Befund:** Mit Stundenwerten trennt das Abklingen Regen und andere Ereignisse kaum. Nach Regenende sind
von einer Erhöhung durch ausgewaschene Radon-Folgeprodukte (Pb-214, Bi-214; Halbwertszeiten 26,8 und 19,9 min) nach
einer Stunde noch rund 43 %, nach zwei Stunden rund 12 % übrig (Bateman-Rechnung, Dosisbeitrag Bi-214 zu Pb-214 etwa
85 zu 15, Annahme). Je nachdem, wann in der Stunde der Regen endet, ergibt reines Abklingen im Stundenmittel ein
Verhältnis zwischen etwa 0,35 und 0,7; hält der Regen an, liegt es höher. Die Zerfallssignatur lässt sich erst mit
den 10-Minuten-Werten der BfS-Datenbank bestimmen.
{bild('abb2_regen.png', 'Beispiel Regenereignis', "Beispiel einer Erhöhung mit Regen: das Regenereignis mit dem höchsten z-Wert in dieser Woche. Linke Achse ODL mit Basislinie und Schwelle, rote Punkte = als Erhöhung markierte Stunden; rechte Achse Niederschlag der nächsten DWD-Station. Was daraus folgt: Regen erzeugt genau die Form, die eine Schwellenprüfung auslöst; erst die Niederschlagsinformation macht daraus „regenbedingt“ statt „lokal, prüfen“.")}
**Eingebaute Fehler:**

| Fehler | Größe | eingebaut | erkannt | 95-%-Bereich | richtig eingeordnet |
|---|---|---|---|---|---|
{chr(10).join(zeilen)}

Präzision der Prüfer-Meldungen je Durchlauf: {', '.join(de(p, 0, True) for p in praez)} (eingebaut je Durchlauf
{st['praezision'][0]['eingebaut']} Fehler in {de(d['mit_stundenwerten'], 0)} Sonden über sieben Tage). Das ist eine
Untergrenze: Auch die „anderen“ Meldungen können echte Auffälligkeiten sein.
{bild('abb3_stundentest.png', 'Trefferquote Stundenwerte', "Trefferquote je eingebautem Fehler über alle fünf Durchläufe, mit 95-%-Vertrauensbereich (Wilson); n = Zahl der eingebauten Fehler, Drift grau. Was daraus folgt: Sprunghafte Fehler ab 20 % der ODL findet schon die einfache Prüfung sicher. Eine schleichende Drift zieht die 24-Stunden-Basislinie mit und bleibt bei 10 bis 20 % meist unerkannt; dafür braucht es einen Erwartungswert aus Nachbarsonden und Wetter statt aus der eigenen Vergangenheit.")}
**Voralarme (nachgebildet):** {h['voralarme']} Ereignisse in sieben Tagen, im Median
{de(h['voralarme_sonden_median'], 0)} Sonden je Ereignis (Liste in `voralarme_stunden.csv`):

| Einordnung (Mehrheit der beteiligten Sonden und Stunden) | Voralarme |
|---|---|
| Regen am nächsten Messer | {vk.get('regen', 0)} |
| Messer hat Werte, meldet keinen Regen („trocken“) | {vk.get('trocken', 0)} |
| teils Regen, teils trocken | {vk.get('gemischt', 0)} |
| keine Messerdaten | {vk.get('ohne_messer', 0)} |

Von den {nicht_regen} Voralarmen ohne Regen an der Mehrheit beruhen {vk.get('ohne_messer', 0)} auf fehlenden
Messerdaten; nur {vk.get('trocken', 0)} sind im Sinne gemessener Werte trocken. Diese sind Kandidaten für
Niederschlag, den eine Punktmessung bis 20 km entfernt nicht sieht, oder für andere Ursachen. Radarniederschlag
(DWD RADOLAN) liegt flächendeckend und zeitnah vor und würde beide Lücken schließen: die Entfernung zum Messer und
das Ende der Stationsreihe.

## 5 Ergebnisse: Tageswerte

Sprungkandidaten auf den echten Daten mit kalibriertem Strafterm: {tg['kandidaten_roh']} an
{tg['sonden_mit_kandidat_roh']} Sonden auf der Reihe allein, {tg['kandidaten_nachbarn']} an
{tg['sonden_mit_kandidat_nachbarn']} Sonden gegen Nachbarn ({de(tg['sonden_mit_referenz'], 0)} Sonden haben genug
Nachbarn; Liste in `sprungkandidaten.csv`). Kandidaten sind keine Befunde: Ob ein Sondenwechsel,
eine Standortänderung oder Bewuchs dahintersteht, zeigen erst die internen Stammdaten.

**Eingebaute Stufen ({de(tg['test']['sonden'], 0)} geeignete Sonden, alle Varianten mit gleichem Alarmbudget):**

| Stufe | eingebaut | erkannt, Reihe allein | erkannt, gegen Nachbarn{kopf_k} |
|---|---|---|---{trenn_k}|
{chr(10).join(sprung_zeilen)}
{bild('abb4_spruenge.png', 'Sprungerkennung', f"Trefferquote für eingebaute Stufen in Tagesreihen, drei Varianten mit demselben Alarmbudget, Fehlerbalken 95 % (Wilson), Punkte zur Lesbarkeit leicht versetzt; rote Linie 80 %. Was daraus folgt: Der Vergleich gegen den Median der Nachbarn findet eine Stufe von 10 % zu {de(sp['nachbarn']['0.1']['trefferquote'], 0, True)} statt {de(sp['roh']['0.1']['trefferquote'], 0, True)}, eine von 5 % zu {de(sp['nachbarn']['0.05']['trefferquote'], 0, True)} statt {de(sp['roh']['0.05']['trefferquote'], 0, True)}. Die Auswahl nach Korrelation der Tagesänderungen ist schlechter ({k10} und {k5}), vermutlich weil diese Änderungen von Rundung (0,001 µSv/h) und Zählrauschen geprägt sind.")}
**Schnee:**

| Schneehöhe | Sonden-Tage | Sonden | Median Abweichung | mittlere Hälfte |
|---|---|---|---|---|
{chr(10).join(schnee_zeilen)}
| schneefrei (Vergleich, jeder 7. Tag) | {de(frei['tage'], 0)} | – | {de(frei['median'], 1, True)} | {de(frei['q25'], 1, True)} bis {de(frei['q75'], 1, True)} |
{bild('abb5_schnee.png', 'Schnee-Effekt', f"Abweichung der Tages-ODL an Tagen mit Schneedecke vom Median der schneefreien Tage derselben Sonde (± 15 Tage), nach Schneehöhe an der nächsten DWD-Station; Kasten = mittlere Hälfte, Linie = Median, Antennen ohne Ausreißer. Was daraus folgt: Die Abweichung wächst mit der Schneehöhe, wie es die Abschirmung der Bodenstrahlung erwarten lässt; gezeigt ist ein Zusammenhang, kein Nachweis der Ursache. Die Klasse über 30 cm beruht auf {de(schnee30.get('tage'), 0)} Sonden-Tagen an {de(schnee30.get('sonden'), 0)} Sonden.")}
## 6 Grenzen

- Ein Jahr Tageswerte erlaubt keine Aussage zu langfristigen Trends; gezeigt ist, wie groß eine Änderung sein muss,
  um gefunden zu werden, und dass der Nachbarvergleich diese Schwelle senkt.
- Das Alarmbudget von {de(tg['alarm_anteil'], 0, True)} der Sonden je Jahr ist eine Annahme; die Zahl echter
  Sondenwechsel und Standortänderungen steht in den Stammdaten des BfS.
- Sieben Tage Stundenwerte sind eine Stichprobe einer Herbstwoche; Gewitterlagen, Schnee und Inversionen sind
  darin nicht oder kaum enthalten.
- Die echten Plausibilisierungsentscheidungen des BfS sind nicht öffentlich. Die Trefferquoten gelten für
  eingebaute Fehler, nicht für die realen Fehlerbilder; die Präzision ist eine Untergrenze.
- Der Regenmesser steht bis zu 20 km von der Sonde entfernt; lokale Schauer verfehlt er. Am Ende der Woche fehlen
  Messerdaten ganz (Abschnitt 2). Die DWD-Daten der Reihe `recent` sind nur eingeschränkt geprüft.

## 7 Reproduzieren

Code und Nachweis: https://github.com/panoherbe/odlscan (AGPL-3.0). Befehle:

    pip install ".[plots]"
    odlscan holen --daten daten
    odlscan auswerten --raw daten/raw/<Abrufdatum> --aus nachweis/<Datum>

Laufzeiten dieses Laufs: Einlesen {de(lz['einlesen_s'], 0)} s, Stundenprüfung {de(lz['stunden_pruefung_s'], 1)} s,
Stundentest {de(lz['stunden_test_s'], 1)} s, Tagesprüfung {de(lz['tage_pruefung_s'], 1)} s, Tagestest
{de(lz['tage_test_s'], 1)} s; Python {r['umgebung']['python']}, NumPy {r['umgebung']['numpy']}, {r['umgebung']['system']}.

Datenquellen: Bundesamt für Strahlenschutz (BfS), ODL-Messnetz, Datenlizenz Deutschland – Namensnennung – 2.0;
Deutscher Wetterdienst (DWD), Open Data, CC BY 4.0.

## 8 Korrekturen gegenüber dem Bericht vom 02.11.2026 (odlscan 0.1.0)

Verfahren, Parameter, Zufallsstartwerte und Rohablage sind unverändert; alle Kennzahlen des Berichts vom 02.11.
ergeben sich wieder genau so. Neu ausgewertet sind die Abdeckung durch Regenmesser, die Einordnung der Voralarme,
die Vergleichsvariante „Korrelations-Nachbarn“ und die Abrufstatistik; geändert sind Angaben und Darstellung.

- **Drift:** Die Zusammenfassung nannte die Trefferquoten für Spitze, Stufe und Absenkung, ohne die Drift zu
  erwähnen; sie steht jetzt getrennt da ({tq('drift|0.2')} bei 20 %, {tq('drift|0.1')} bei 10 %).
- **Regenmesser-Abdeckung:** Der Bericht vom 02.11. nannte die übrigen 12 Voralarme „regional, aber der nächste
  Regenmesser meldet nichts“ und alle {e.get('regional', 0)} regionalen Erhöhungen „ohne Regen am Messer“. Fehlende
  Messerdaten wurden dabei wie „kein Regen“ gezählt. Jetzt ist ausgewiesen, wo Messerdaten fehlen (Abschnitt 4).
- **Abklingen:** „klingen innerhalb einer Stunde ab“ ersetzt durch die Bateman-Werte (rund 43 % nach einer Stunde,
  12 % nach zwei Stunden).
- **Schnee:** Die Spalte „Tage“ zählt Sonden-Tage; so heißt sie jetzt, mit der Zahl der Sonden je Klasse.
- **Kalibrierfaktor 2025:** „laut BfS geringe Erhöhung“ ersetzt durch die Angabe des BfS (etwa 14–25 %).
- **Abruf:** Das Testprotokoll vom 02.11. nannte „5.297 Dateien, 84 MB“, also Manifest-Einträge und den belegten
  Plattenplatz der Ablage; jetzt stehen Abrufe, Volumen wie geliefert und Dateigröße der Ablage getrennt da
  (Abschnitt 2).
- **Korrelations-Nachbarn:** Die verworfene Variante war im Protokoll vom 02.11. ohne Code berichtet (78 % statt
  96 %; jene Umsetzung ist nicht erhalten). Sie ist jetzt Teil des Codes und neu gemessen: {k10} bei 10 %, {k5} bei
  5 %; sie bleibt schlechter als der Median der Nachbarn und verworfen.
- **Abbildungen:** nummeriert, mit Unterschrift, Fallzahlen und Vertrauensbereichen, 300 dpi; die begrenzte Farbskala
  in Abb. 1 ist gekennzeichnet, die rechte Achse in Abb. 2 sichtbar (vorher lasen sich ihre Teilstriche wie
  Minuszeichen), der Titel von Abb. 5 behauptet keine Ursache mehr.
"""
