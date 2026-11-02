"""Rohdateien lesen und auf gemeinsame Zeitraster legen (Stunde bzw. Tag, UTC)."""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from pathlib import Path

import numpy as np


def _json(pfad: Path) -> dict:
    with gzip.open(pfad, "rt", encoding="utf-8") as f:
        return json.load(f)


def sonden(pfad: Path) -> list[dict]:
    """Messstellenliste (Layer odlinfo_sitelist)."""
    aus = []
    for f in _json(pfad)["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        aus.append({"kenn": p["kenn"], "id": p["id"], "name": p["name"], "lat": float(lat), "lon": float(lon),
                    "hoehe": p.get("height_above_sea"), "status": p.get("site_status"), "knoten": p.get("kid")})
    aus.sort(key=lambda s: s["kenn"])
    return aus


def zeitreihe(pfad: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(Beginn der Messperiode als datetime64[m] UTC, Wert in µSv/h, geprüft 1/2) einer ODL-Zeitreihe."""
    t, v, g = [], [], []
    for f in _json(pfad)["features"]:
        p = f["properties"]
        if p.get("value") is None:
            continue
        t.append(np.datetime64(p["start_measure"].rstrip("Z"), "m"))
        v.append(float(p["value"]))
        g.append(int(p.get("validated") or 0))
    o = np.argsort(np.array(t, dtype="datetime64[m]"))
    return np.array(t, dtype="datetime64[m]")[o], np.array(v)[o], np.array(g)[o]


def dwd_stationen(text: bytes) -> list[dict]:
    """Stationsbeschreibung des DWD (feste Spalten, Latin-1): ID, von, bis, Höhe, Breite, Länge, Name."""
    aus = []
    for zeile in text.decode("latin-1").splitlines()[2:]:
        t = zeile.split()
        if len(t) < 7 or not t[0].isdigit():
            continue
        aus.append({"id": int(t[0]), "von": t[1], "bis": t[2], "hoehe": float(t[3]), "lat": float(t[4]),
                    "lon": float(t[5]), "name": t[6]})
    return aus


def dwd_produkt(zip_pfad: Path, spalten: list[str]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """MESS_DATUM und die gewünschten Spalten aus produkt_*.txt im DWD-ZIP; -999 wird NaN.

    Stundenwerte (JJJJMMTTHH, UTC) werden zu datetime64[h] und bezeichnen das Ende der Stunde, Tageswerte
    (JJJJMMTT) zu datetime64[D].
    """
    with zipfile.ZipFile(zip_pfad) as z:
        name = next(n for n in z.namelist() if n.startswith("produkt_"))
        text = io.TextIOWrapper(z.open(name), encoding="latin-1").read()
    zeilen = [z for z in text.splitlines() if z.strip()]
    kopf = [k.strip() for k in zeilen[0].split(";")]
    idx = {k: i for i, k in enumerate(kopf)}
    zeiten, werte = [], {s: [] for s in spalten}
    for z in zeilen[1:]:
        t = z.split(";")
        d = t[idx["MESS_DATUM"]].strip()
        if len(d) == 10:
            zeiten.append(np.datetime64(f"{d[:4]}-{d[4:6]}-{d[6:8]}T{d[8:10]}", "h"))
        else:
            zeiten.append(np.datetime64(f"{d[:4]}-{d[4:6]}-{d[6:8]}", "D"))
        for s in spalten:
            x = float(t[idx[s]])
            werte[s].append(np.nan if x <= -999 else x)
    return np.array(zeiten), {s: np.array(v) for s, v in werte.items()}


def raster(reihen: dict[str, tuple[np.ndarray, np.ndarray]], schritt: str) -> tuple[np.ndarray, np.ndarray]:
    """Mehrere (Zeit, Wert)-Reihen auf ein gemeinsames lückenloses Raster legen: (Zeiten, Matrix Sonde × Zeit)."""
    alle = [t.astype(f"datetime64[{schritt}]") for t, _ in reihen.values() if len(t)]
    t0, t1 = min(a.min() for a in alle), max(a.max() for a in alle)
    zeiten = np.arange(t0, t1 + np.timedelta64(1, schritt), dtype=f"datetime64[{schritt}]")
    m = np.full((len(reihen), len(zeiten)), np.nan)
    for i, (t, v) in enumerate(reihen.values()):
        if len(t):
            m[i, (t.astype(f"datetime64[{schritt}]") - t0).astype(int)] = v
    return zeiten, m


def auf_raster(zeiten: np.ndarray, t: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Eine Reihe (t, v) auf ein vorhandenes Raster legen; was außerhalb liegt, fällt weg."""
    aus = np.full(len(zeiten), np.nan)
    k = (t.astype(zeiten.dtype) - zeiten[0]).astype(int)
    ok = (k >= 0) & (k < len(zeiten))
    aus[k[ok]] = v[ok]
    return aus


class Datensatz:
    """Alles, was die Auswertung braucht, aus einer Rohablage (raw/<abrufdatum>/)."""

    def __init__(self, raw: Path):
        self.raw = raw
        self.sonden = [s for s in sonden(raw / "bfs/odlinfo_sitelist.json.gz") if s["status"] == 1]
        stunde, tag = {}, {}
        for s in self.sonden:
            for layer, ziel in (("odlinfo_timeseries_odl_1h", stunde), ("odlinfo_timeseries_odl_24h", tag)):
                p = raw / f"bfs/{layer}/{s['kenn']}.json.gz"
                t, v, _ = zeitreihe(p) if p.exists() else (np.array([], "datetime64[m]"), np.array([]), None)
                # Stundenwert: Ende der Messstunde, wie beim DWD; Tageswert: Kalendertag des Beginns (UTC)
                ziel[s["kenn"]] = (t + np.timedelta64(60, "m"), v) if layer.endswith("1h") else (t, v)
        self.stunden, self.odl_h = raster(stunde, "h")
        self.tage, self.odl_d = raster(tag, "D")
        self.lat = np.array([s["lat"] for s in self.sonden])
        self.lon = np.array([s["lon"] for s in self.sonden])
        self.hoehe = np.array([np.nan if s["hoehe"] is None else s["hoehe"] for s in self.sonden], dtype=float)
        self.regen_h = self._dwd("stunde", self.stunden, "R1")
        self.regen_d = self._dwd("tag", self.tage, "RS")
        self.schnee_d = self._dwd("tag", self.tage, "SH_TAG")

    def _dwd(self, art: str, zeiten: np.ndarray, spalte: str) -> np.ndarray:
        m = np.full((len(self.sonden), len(zeiten)), np.nan)
        zpfad = self.raw / f"dwd/{art}/zuordnung.json"
        if not zpfad.exists():
            return m
        zuordnung = json.loads(zpfad.read_text())
        cache: dict[int, np.ndarray] = {}
        for i, s in enumerate(self.sonden):
            sid = zuordnung.get(s["kenn"])
            if sid is None:
                continue
            if sid not in cache:
                treffer = list((self.raw / f"dwd/{art}").glob(f"*_{sid:05d}_akt.zip"))
                if not treffer:
                    cache[sid] = np.full(len(zeiten), np.nan)
                else:
                    t, w = dwd_produkt(treffer[0], [spalte])
                    cache[sid] = auf_raster(zeiten, t, w[spalte])
            m[i] = cache[sid]
        return m
