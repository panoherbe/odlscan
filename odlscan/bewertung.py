"""Messen, was die Verfahren leisten: künstliche Fehler in echte Reihen einbauen und wiederfinden.

Stunden: Je Durchlauf werden in zufällig gewählte Sonden je ein Fehler an einer trockenen, unauffälligen Stelle
eingebaut (kein Regen und keine Markierung von t0−3 bis t0+14, alle Werte von t0−24 bis t0+14 vorhanden). Gemessen
werden je Fehlerart und -größe die Trefferquote (Markierung der erwarteten Art im Prüffenster) und die richtige
Einordnung, über alle Sonden die Präzision der Meldungen, die ein Prüfer ansehen müsste („lokal“, Absenkung,
Hänger), mit dem echten Hintergrund der übrigen Sonden.

Tage: Je Durchlauf wird in zufällig gewählte Sonden eine Stufe (relative Änderung ab t0) eingebaut; Treffer ist ein
Sprung gleichen Vorzeichens innerhalb ± 10 Tagen um t0 mit mindestens der halben Größe. Der Strafterm je Variante
ist vorher auf das Alarmbudget kalibriert (trend.kalibrieren), damit beide Varianten gleich oft melden.
"""

from __future__ import annotations

import numpy as np

from . import anomalie, trend

STUNDEN_FEHLER = {
    "spitze": [0.05, 0.10, 0.20, 0.50],
    "stufe": [0.05, 0.10, 0.20],
    "drift": [0.10, 0.20, 0.40],
    "absenkung": [0.10, 0.20, 0.40],
    "haenger": [0.0],
}
ERWARTET = {"spitze": "oben", "stufe": "oben", "drift": "oben", "absenkung": "unten", "haenger": "haenger"}
TAGES_STUFEN = [0.005, 0.01, 0.02, 0.03, 0.05, 0.10]


def einbauen(x: np.ndarray, art: str, t0: int, groesse: float) -> tuple[np.ndarray, int, int]:
    """Fehler einbauen; Rückgabe: veränderte Reihe und Prüffenster (von, bis einschließlich)."""
    y = x.copy()
    ref = float(np.nanmedian(x))
    n = len(y)
    if art == "spitze":
        y[t0] += groesse * ref
        return y, t0, min(n - 1, t0 + 1)
    if art == "stufe":
        y[t0:] += groesse * ref
        return y, t0, min(n - 1, t0 + 3)
    if art == "drift":
        lang = min(24, n - t0)
        y[t0:t0 + lang] += groesse * ref * np.arange(1, lang + 1) / 24
        y[t0 + lang:] += groesse * ref
        return y, t0, min(n - 1, t0 + 30)
    if art == "absenkung":
        y[t0:] -= groesse * ref
        return y, t0, min(n - 1, t0 + 3)
    if art == "haenger":
        y[t0:t0 + 12] = y[t0]
        return y, t0, min(n - 1, t0 + 11)
    raise ValueError(art)


def _ruhige_stellen(x, e, nass, messer, start=30, nach=14) -> np.ndarray:
    n = len(x)
    flag = e["oben"] | e["unten"] | e["haenger"]
    kand = []
    for t0 in range(start, n - nach):
        a, b = t0 - 3, t0 + nach + 1
        if flag[a:b].any() or nass[a:b].any() or not messer[a:b].all() or np.isnan(x[t0 - 24:b]).any():
            continue
        kand.append(t0)
    return np.array(kand, int)


def _relevant(ev: dict) -> bool:
    return ev["klasse"] in ("lokal", "absenkung", "haenger")


def stunden_test(odl: np.ndarray, erg: list[dict], regen: np.ndarray, nb: list[np.ndarray],
                 durchlaeufe: int = 5, je_lauf: int = 300) -> dict:
    nass, messer = anomalie.regen_maske(regen)
    nachb = anomalie.nachbar_zahl(erg, nb)
    basis_ev = {i: anomalie.ereignisse(i, odl[i], erg[i], nass[i], messer[i], nachb[i]) for i in range(len(erg))}
    stellen = {i: _ruhige_stellen(odl[i], erg[i], nass[i], messer[i]) for i in range(len(erg))}
    geeignet = [i for i, s in stellen.items() if len(s)]
    arten = [(a, g) for a, gs in STUNDEN_FEHLER.items() for g in gs]
    zaehler = {f"{a}|{g}": {"n": 0, "erkannt": 0, "richtig_eingeordnet": 0} for a, g in arten}
    praez = []
    for lauf in range(durchlaeufe):
        rng = np.random.default_rng(1000 + lauf)
        wahl = rng.choice(geeignet, size=min(je_lauf, len(geeignet)), replace=False)
        tp = fp = 0
        geaendert = {}
        for i in wahl:
            art, g = arten[rng.integers(len(arten))]
            t0 = int(rng.choice(stellen[i]))
            y, a, b = einbauen(odl[i], art, t0, g)
            e = anomalie.erkennen(y)
            ev = anomalie.ereignisse(int(i), y, e, nass[i], messer[i], nachb[i])
            geaendert[int(i)] = (ev, a, b)
            z = zaehler[f"{art}|{g}"]
            z["n"] += 1
            treffer = [v for v in ev if v["art"] == ERWARTET[art] and v["von"] <= b and v["bis"] >= a]
            if treffer:
                z["erkannt"] += 1
                soll = {"oben": "lokal", "unten": "absenkung", "haenger": "haenger"}[ERWARTET[art]]
                if any(v["klasse"] == soll for v in treffer):
                    z["richtig_eingeordnet"] += 1
        for i in range(len(erg)):
            if i in geaendert:
                ev, a, b = geaendert[i]
                for v in filter(_relevant, ev):
                    if v["von"] <= b and v["bis"] >= a:
                        tp += 1
                    else:
                        fp += 1
            else:
                fp += sum(map(_relevant, basis_ev[i]))
        praez.append({"lauf": lauf, "eingebaut": len(wahl), "treffer_meldungen": tp, "andere_meldungen": fp,
                      "praezision": tp / (tp + fp) if tp + fp else None})
    for z in zaehler.values():
        z["trefferquote"] = z["erkannt"] / z["n"] if z["n"] else None
        z["einordnung"] = z["richtig_eingeordnet"] / z["erkannt"] if z["erkannt"] else None
    return {"je_fehler": zaehler, "praezision": praez, "sonden_mit_ruhigen_stellen": len(geeignet)}


def tages_test(logodl: np.ndarray, ref: np.ndarray, schnee: np.ndarray, strafe: dict[str, float],
               durchlaeufe: int = 5, je_lauf: int = 300, min_tage: int = 300,
               ref_korrelation: np.ndarray | None = None) -> dict:
    """Geeignet sind Sonden mit Reihe und Nachbarreferenz an mindestens `min_tage` Tagen. Die Vergleichsvariante
    „korrelation“ (falls übergeben) läuft auf denselben eingebauten Stufen, nur wo ihre Referenz ebenso lang ist;
    die Zufallsfolge ist dieselbe wie ohne sie."""
    n = logodl.shape[1]
    geeignet = [i for i in range(len(logodl)) if np.isfinite(logodl[i]).sum() >= min_tage
                and np.isfinite(ref[i]).sum() >= min_tage]
    varianten = ("roh", "nachbarn") + (("korrelation",) if ref_korrelation is not None else ())
    erg = {v: {f"{s}": {"n": 0, "erkannt": 0} for s in TAGES_STUFEN} for v in varianten}
    for lauf in range(durchlaeufe):
        rng = np.random.default_rng(2000 + lauf)
        for i in rng.choice(geeignet, size=min(je_lauf, len(geeignet)), replace=False):
            s = TAGES_STUFEN[rng.integers(len(TAGES_STUFEN))]
            t0 = int(rng.integers(60, n - 60))
            y = logodl[i].copy()
            y[t0:] += np.log1p(s)
            paare = [("roh", None), ("nachbarn", ref[i])]
            if ref_korrelation is not None and np.isfinite(ref_korrelation[i]).sum() >= min_tage:
                paare.append(("korrelation", ref_korrelation[i]))
            for var, r in paare:
                sp = trend.spruenge(trend.reihe(y, r, schnee[i]), strafe=strafe[var])
                z = erg[var][f"{s}"]
                z["n"] += 1
                if any(abs(p["index"] - t0) <= 10 and p["hoehe"] >= np.log1p(s) / 2 for p in sp):
                    z["erkannt"] += 1
    for var in erg.values():
        for z in var.values():
            z["trefferquote"] = z["erkannt"] / z["n"] if z["n"] else None
    return {"je_stufe": erg, "sonden": len(geeignet)}
