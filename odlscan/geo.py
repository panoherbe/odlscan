"""Abstände auf der Kugel und Nachbarschaften von Messstellen."""

from __future__ import annotations

import numpy as np

ERDRADIUS_KM = 6371.0


def abstand_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Haversine-Abstandsmatrix (len(lat1) × len(lat2)) in km."""
    p1, l1 = np.radians(np.asarray(lat1, float))[:, None], np.radians(np.asarray(lon1, float))[:, None]
    p2, l2 = np.radians(np.asarray(lat2, float))[None, :], np.radians(np.asarray(lon2, float))[None, :]
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin((l2 - l1) / 2) ** 2
    return 2 * ERDRADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def nachbarn(lat, lon, radius_km: float, hoehe=None, max_hoehendiff: float | None = None) -> list[np.ndarray]:
    """Je Messstelle die Indizes der anderen Messstellen im Umkreis (optional mit ähnlicher Höhe)."""
    d = abstand_km(lat, lon, lat, lon)
    ok = (d <= radius_km) & ~np.eye(len(d), dtype=bool)
    if hoehe is not None and max_hoehendiff is not None:
        h = np.asarray(hoehe, float)
        dh = np.abs(h[:, None] - h[None, :])
        ok &= ~(dh > max_hoehendiff)  # unbekannte Höhe schließt nicht aus
    return [np.flatnonzero(r) for r in ok]
