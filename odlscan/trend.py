"""Tageswerte: Sprungstellen (Sondenwechsel, Standortänderung) und Einfluss der Schneedecke.

Sprungstellen: binäre Segmentierung des Mittelwerts auf log(ODL), Mindestsegment 21 Tage, höchstens 3 Sprünge,
Strafterm c · σ² · ln n (σ robust aus den Tagesdifferenzen). Echte Tagesreihen sind autokorreliert; mit dem
klassischen c = 3 hätte fast jede Sonde Sprünge. Deshalb wird c je Variante kalibriert: so, dass auf den echten
Reihen ALARM_ANTEIL der Sonden einen Sprungkandidaten zeigt (Alarmbudget). Bei gleichem Budget wird dann die
Trefferquote für eingebaute Stufen verglichen. Zwei Varianten:

- „roh“: die Reihe der Sonde selbst;
- „gegen Nachbarn“: log(ODL) der Sonde minus Median der log(ODL) ihrer Nachbarn (≤ 50 km, Höhenunterschied
  ≤ 300 m, mindestens 3). Regionale Einflüsse (Bodenfeuchte, Schnee, Witterung) heben sich dabei weitgehend auf,
  ein Sondenwechsel nicht. Das ist das in der Klimatologie übliche Homogenisieren gegen Referenzreihen.
- „Korrelations-Nachbarn“ (Vergleichsvariante, im Bericht als verworfen geführt): Referenz aus den fünf Sonden im
  Umkreis von 75 km, deren Tagesänderungen am stärksten mit denen der Sonde korrelieren.

Tage mit Schneedecke an der nächsten DWD-Station werden vor der Segmentierung ausgeblendet.

Schnee: relative Abweichung eines Tages vom Median der schneefreien Tage derselben Sonde im Fenster ± 15 Tage,
gruppiert nach Schneehöhe an der nächsten DWD-Station.
"""

from __future__ import annotations

import warnings

import numpy as np

MIN_SEGMENT = 21
MAX_SPRUENGE = 3
STRAFE = 3.0
ALARM_ANTEIL = 0.10
NACHBAR_KM = 50.0
NACHBAR_DH = 300.0
MIN_NACHBARN = 3
SCHNEE_FENSTER = 15
SCHNEE_KLASSEN = [(1, 5), (6, 15), (16, 30), (31, 1000)]
KORR_KM = 75.0
KORR_ANZAHL = 5
KORR_MIN_TAGE = 200


def _sigma(y: np.ndarray) -> float:
    d = np.diff(y)
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2)) if len(d) > 2 else np.nan


def _bester_schnitt(c1: np.ndarray, c2: np.ndarray, a: int, e: int, min_seg: int) -> tuple[int, float]:
    """Bester Schnitt k in [a+min_seg, e-min_seg] für y[a:e] über kumulierte Summen; Gewinn an Quadratsumme."""
    n = e - a
    ks = np.arange(a + min_seg, e - min_seg + 1)
    if len(ks) == 0:
        return -1, 0.0
    s_all, q_all = c1[e] - c1[a], c2[e] - c2[a]
    sse_all = q_all - s_all ** 2 / n
    sl, ql, nl = c1[ks] - c1[a], c2[ks] - c2[a], ks - a
    sr, qr, nr = s_all - sl, q_all - ql, e - ks
    gewinn = sse_all - (ql - sl ** 2 / nl) - (qr - sr ** 2 / nr)
    j = int(np.argmax(gewinn))
    return int(ks[j]), float(gewinn[j])


def spruenge(y: np.ndarray, min_seg: int = MIN_SEGMENT, max_spruenge: int = MAX_SPRUENGE,
             strafe: float = STRAFE) -> list[dict]:
    """Sprungstellen in y (NaN erlaubt). Rückgabe: Index im Original und Sprunghöhe (Mittel rechts − links)."""
    ok = np.flatnonzero(np.isfinite(y))
    v = y[ok]
    n = len(v)
    if n < 2 * min_seg:
        return []
    s = _sigma(v)
    if not np.isfinite(s) or s == 0:
        return []
    schwelle = strafe * s ** 2 * np.log(n)
    c1 = np.concatenate([[0.0], np.cumsum(v)])
    c2 = np.concatenate([[0.0], np.cumsum(v * v)])
    schnitte, offen = [], [(0, n)]
    while offen and len(schnitte) < max_spruenge:
        kand = [(*_bester_schnitt(c1, c2, a, e, min_seg), a, e) for a, e in offen]
        k, g, a, e = max(kand, key=lambda t: t[1])
        if k < 0 or g <= schwelle:
            break
        schnitte.append(k)
        offen.remove((a, e))
        offen += [(a, k), (k, e)]
    schnitte.sort()
    grenzen = [0] + schnitte + [n]
    aus = []
    for i, k in enumerate(schnitte):
        links, rechts = v[grenzen[i]:k], v[k:grenzen[i + 2]]
        aus.append({"index": int(ok[k]), "hoehe": float(rechts.mean() - links.mean())})
    return aus


def statistik(y: np.ndarray, min_seg: int = MIN_SEGMENT) -> float:
    """Gewinn des besten einzelnen Schnitts relativ zu σ² · ln n: der Strafterm-Faktor, ab dem kein Sprung mehr
    gemeldet würde. NaN, wenn die Reihe zu kurz ist."""
    v = y[np.isfinite(y)]
    n = len(v)
    if n < 2 * min_seg:
        return np.nan
    s = _sigma(v)
    if not np.isfinite(s) or s == 0:
        return np.nan
    c1 = np.concatenate([[0.0], np.cumsum(v)])
    c2 = np.concatenate([[0.0], np.cumsum(v * v)])
    _, g = _bester_schnitt(c1, c2, 0, n, min_seg)
    return g / (s ** 2 * np.log(n))


def kalibrieren(reihen: list[np.ndarray], anteil: float = ALARM_ANTEIL) -> float:
    """Strafterm-Faktor, bei dem `anteil` der Reihen mindestens einen Sprung zeigt."""
    st = np.array([statistik(y) for y in reihen])
    return float(np.nanpercentile(st, 100 * (1 - anteil)))


def referenz(logodl: np.ndarray, nb: list[np.ndarray]) -> np.ndarray:
    """Median der log(ODL) der Nachbarn je Tag; NaN, wenn weniger als MIN_NACHBARN Nachbarn."""
    aus = np.full(logodl.shape, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i, j in enumerate(nb):
            if len(j) >= MIN_NACHBARN:
                aus[i] = np.nanmedian(logodl[j], axis=0)
    return aus


def referenz_korrelation(logodl: np.ndarray, kandidaten: list[np.ndarray], anzahl: int = KORR_ANZAHL,
                         min_tage: int = KORR_MIN_TAGE) -> np.ndarray:
    """Median der log(ODL) der `anzahl` Kandidaten, deren Tagesänderungen am stärksten mit denen der Sonde
    korrelieren (Pearson, mindestens `min_tage` gemeinsame Tage); NaN, wenn weniger als MIN_NACHBARN übrig bleiben."""
    d = np.diff(logodl, axis=1)
    aus = np.full(logodl.shape, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i, j in enumerate(kandidaten):
            if len(j) < MIN_NACHBARN:
                continue
            ok = np.isfinite(d[i]) & np.isfinite(d[j])
            n = ok.sum(axis=1)
            x = np.where(ok, d[i], np.nan)
            y = np.where(ok, d[j], np.nan)
            xm = x - np.nanmean(x, axis=1, keepdims=True)
            ym = y - np.nanmean(y, axis=1, keepdims=True)
            r = np.nansum(xm * ym, axis=1) / np.sqrt(np.nansum(xm ** 2, axis=1) * np.nansum(ym ** 2, axis=1))
            r = np.where((n >= min_tage) & np.isfinite(r), r, -np.inf)
            wahl = np.argsort(-r)[:anzahl]
            beste = j[wahl[np.isfinite(r[wahl])]]
            if len(beste) >= MIN_NACHBARN:
                aus[i] = np.nanmedian(logodl[beste], axis=0)
    return aus


def reihe(logodl_i: np.ndarray, ref_i: np.ndarray | None, schnee_i: np.ndarray) -> np.ndarray:
    y = logodl_i.copy() if ref_i is None else logodl_i - ref_i
    with np.errstate(invalid="ignore"):
        y[schnee_i > 0] = np.nan
    return y


def schnee_effekt(odl: np.ndarray, schnee: np.ndarray) -> dict:
    """Relative Abweichung an Schneetagen gegenüber schneefreien Tagen derselben Sonde (± 15 Tage)."""
    werte = {k: [] for k in SCHNEE_KLASSEN}
    sonden = {k: set() for k in SCHNEE_KLASSEN}
    frei_alle = []
    n = odl.shape[1]
    for i in range(odl.shape[0]):
        x, sh = odl[i], schnee[i]
        if np.all(np.isnan(sh)):
            continue
        with np.errstate(invalid="ignore"):
            frei = (sh == 0) & np.isfinite(x)
            tage = np.flatnonzero((sh >= 1) & np.isfinite(x))
        for t in tage:
            a, e = max(0, t - SCHNEE_FENSTER), min(n, t + SCHNEE_FENSTER + 1)
            ref = x[a:e][frei[a:e]]
            if len(ref) < 5:
                continue
            d = x[t] / np.median(ref) - 1
            for k in SCHNEE_KLASSEN:
                if k[0] <= sh[t] <= k[1]:
                    werte[k].append(d)
                    sonden[k].add(i)
        # zum Vergleich: schneefreie Tage gegen ihren eigenen Fenster-Median
        for t in np.flatnonzero(frei)[::7]:
            a, e = max(0, t - SCHNEE_FENSTER), min(n, t + SCHNEE_FENSTER + 1)
            ref = x[a:e][frei[a:e]]
            if len(ref) >= 5:
                frei_alle.append(x[t] / np.median(ref) - 1)
    aus = {}
    for k in SCHNEE_KLASSEN:
        w = np.array(werte[k])
        name = f"{k[0]}–{k[1]} cm" if k[1] < 1000 else f"> {k[0] - 1} cm"
        aus[name] = {"tage": int(len(w)), "sonden": len(sonden[k]),
                     "median": float(np.median(w)) if len(w) else None,
                     "q25": float(np.percentile(w, 25)) if len(w) else None,
                     "q75": float(np.percentile(w, 75)) if len(w) else None,
                     "werte": w}
    f = np.array(frei_alle)
    aus["schneefrei"] = {"tage": int(len(f)), "median": float(np.median(f)) if len(f) else None,
                         "q25": float(np.percentile(f, 25)) if len(f) else None,
                         "q75": float(np.percentile(f, 75)) if len(f) else None, "werte": f}
    return aus
