"""Plausibilitätsprüfung der Stundenwerte: Erhöhung, Absenkung, Hänger; Einordnung über Regen und Nachbarsonden.

Verfahren je Sonde (bewusst einfach und nachvollziehbar, damit es als Referenz für ML-Verfahren dient):

- Basislinie b(t) = Median der vorausgehenden 24 Stundenwerte (kausal: nutzt nur Vergangenheit, wie ein Dienst im
  Betrieb). Median, weil Regenspitzen ihn kaum verschieben.
- Streuung s = 1,4826 · MAD der Residuen x − b über die Sonde (robust gegen die Spitzen selbst), mindestens
  0,002 µSv/h (Auflösung der veröffentlichten Werte 0,001 µSv/h).
- z = (x − b) / s. Erhöhung: z ≥ 4 und x − b ≥ 0,005 µSv/h; Absenkung: z ≤ −4 und x − b ≤ −0,005 µSv/h;
  Hänger: mindestens 6 gleiche Werte in Folge.

Einordnung einer Erhöhung: „regen“, wenn die nächste DWD-Station (≤ 20 km) in den Stunden t−2 … t+1 mindestens
0,1 mm meldet; sonst „regional“, wenn mindestens eine Nachbarsonde (≤ 30 km) in t−1 … t+1 z ≥ 3 zeigt; sonst „lokal“
(technisch prüfen). Physikalischer Zusatz: Regen wäscht Radon-Folgeprodukte (Pb-214, Bi-214, Halbwertszeiten
26,8 und 19,9 min) aus; die Erhöhung klingt nach Regenende binnen Stunden ab. Das Abklingverhältnis
(x(t+1) − b) / (x(t) − b) an der Spitze wird je Ereignis mitgeschrieben.
"""

from __future__ import annotations

import warnings

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

FENSTER = 24
MIN_GUELTIG = 12
Z_SCHWELLE = 4.0
Z_NACHBAR = 3.0
MIN_DIFF = 0.005  # µSv/h
SIGMA_MIN = 0.002  # µSv/h
HAENGER = 6
REGEN_MM = 0.1
REGEN_VOR, REGEN_NACH = 2, 1
VORALARM_KM = 30.0


def basislinie(x: np.ndarray, fenster: int = FENSTER, min_gueltig: int = MIN_GUELTIG) -> np.ndarray:
    b = np.full(len(x), np.nan)
    if len(x) <= fenster:
        return b
    w = sliding_window_view(x[:-1], fenster)
    n = np.sum(~np.isnan(w), axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(w, axis=1)
    b[fenster:] = np.where(n >= min_gueltig, med, np.nan)
    return b


def laeufe(maske: np.ndarray) -> list[tuple[int, int]]:
    """Zusammenhängende True-Abschnitte als (Anfang, Ende einschließlich)."""
    m = np.concatenate([[False], np.asarray(maske, bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))


def haenger(x: np.ndarray, mindestens: int = HAENGER) -> np.ndarray:
    gleich = np.zeros(len(x), bool)
    gleich[1:] = (x[1:] == x[:-1]) & ~np.isnan(x[1:])
    aus = np.zeros(len(x), bool)
    for a, e in laeufe(gleich):
        if e - a + 2 >= mindestens:  # e - a + 1 Gleichheiten = e - a + 2 Werte
            aus[a - 1:e + 1] = True
    return aus


def erkennen(x: np.ndarray) -> dict[str, np.ndarray | float]:
    b = basislinie(x)
    r = x - b
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = 1.4826 * np.nanmedian(np.abs(r - np.nanmedian(r)))
    s = SIGMA_MIN if not np.isfinite(s) else max(float(s), SIGMA_MIN)
    z = r / s
    with np.errstate(invalid="ignore"):
        oben = (z >= Z_SCHWELLE) & (r >= MIN_DIFF)
        unten = (z <= -Z_SCHWELLE) & (r <= -MIN_DIFF)
    return {"b": b, "s": s, "z": z, "oben": oben, "unten": unten, "haenger": haenger(x)}


def erkennen_alle(odl: np.ndarray) -> list[dict]:
    return [erkennen(x) for x in odl]


def _verbreitern(m: np.ndarray, vor: int, nach: int) -> np.ndarray:
    """m[:, t] wird True, wenn m im Fenster t−vor … t+nach True ist."""
    aus = m.copy()
    for k in range(1, vor + 1):
        aus[:, k:] |= m[:, :-k]
    for k in range(1, nach + 1):
        aus[:, :-k] |= m[:, k:]
    return aus


def regen_maske(regen: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(Regen im Fenster t−2 … t+1, Regenmesser hat im Fenster überhaupt Werte)."""
    with np.errstate(invalid="ignore"):
        nass = regen >= REGEN_MM
    return _verbreitern(nass, REGEN_VOR, REGEN_NACH), _verbreitern(~np.isnan(regen), REGEN_VOR, REGEN_NACH)


def nachbar_zahl(erg: list[dict], nb: list[np.ndarray]) -> np.ndarray:
    z = np.array([e["z"] for e in erg])
    with np.errstate(invalid="ignore"):
        hoch = _verbreitern(z >= Z_NACHBAR, 1, 1)
    return np.array([hoch[j].sum(axis=0) if len(j) else np.zeros(z.shape[1], int) for j in nb])


def ereignisse(i: int, x: np.ndarray, e: dict, nass: np.ndarray, messer: np.ndarray, nachb: np.ndarray) -> list[dict]:
    """Ereignisse einer Sonde: zusammenhängende markierte Stunden je Art, eingeordnet an der Spitze."""
    aus = []
    for art in ("oben", "unten", "haenger"):
        for a, en in laeufe(e[art]):
            if art == "haenger":
                spitze = a
            else:
                zz = e["z"][a:en + 1]
                spitze = a + int(np.nanargmax(np.abs(zz)))
            klasse = {"unten": "absenkung"}.get(art, art)
            if art == "oben":
                klasse = "regen" if nass[spitze] else ("regional" if nachb[spitze] >= 1 else "lokal")
            abkling = np.nan
            if art == "oben" and spitze + 1 < len(x) and np.isfinite(x[spitze + 1]):
                abkling = (x[spitze + 1] - e["b"][spitze]) / (x[spitze] - e["b"][spitze])
            aus.append({"sonde": i, "art": art, "klasse": klasse, "von": int(a), "bis": int(en),
                        "spitze": int(spitze), "z": float(e["z"][spitze]) if art != "haenger" else np.nan,
                        "messer": bool(messer[spitze]), "abkling": float(abkling)})
    return aus


def alle_ereignisse(odl: np.ndarray, erg: list[dict], regen: np.ndarray, nb: list[np.ndarray]) -> list[dict]:
    nass, messer = regen_maske(regen)
    nachb = nachbar_zahl(erg, nb)
    aus = []
    for i, e in enumerate(erg):
        aus += ereignisse(i, odl[i], e, nass[i], messer[i], nachb[i])
    return aus


def voralarme(erg: list[dict], regen: np.ndarray, nb30: list[np.ndarray]) -> list[dict]:
    """Nachbildung der Voralarm-Regel: zwei Sonden < 30 km mit Erhöhung innerhalb einer Stunde.

    Knoten sind (Sonde, Stunde) mit Erhöhung; Kanten verbinden Knoten derselben oder benachbarter Sonden mit
    höchstens einer Stunde Abstand. Ein Voralarm ist eine Zusammenhangskomponente mit mindestens zwei Sonden.
    Die Schwelle ist hier z ≥ 4, nicht der standortspezifische Schwellenwert des BfS (nicht öffentlich).
    """
    nass, _ = regen_maske(regen)
    oben = np.array([e["oben"] for e in erg])
    knoten = [(int(i), int(t)) for i, t in zip(*np.nonzero(oben))]
    index = {k: n for n, k in enumerate(knoten)}
    eltern = list(range(len(knoten)))

    def wurzel(a):
        while eltern[a] != a:
            eltern[a] = eltern[eltern[a]]
            a = eltern[a]
        return a

    for (i, t), n in index.items():
        for j in np.concatenate([[i], nb30[i]]):
            for dt in (-1, 0, 1):
                m = index.get((int(j), t + dt))
                if m is not None and m != n:
                    eltern[wurzel(m)] = wurzel(n)
    gruppen: dict[int, list] = {}
    for (i, t), n in index.items():
        gruppen.setdefault(wurzel(n), []).append((int(i), int(t)))
    aus = []
    for g in gruppen.values():
        sonden = {i for i, _ in g}
        if len(sonden) < 2:
            continue
        aus.append({"sonden": len(sonden), "knoten": len(g), "von": min(t for _, t in g),
                    "bis": max(t for _, t in g), "regen_anteil": float(np.mean([nass[i, t] for i, t in g]))})
    return sorted(aus, key=lambda v: v["von"])
