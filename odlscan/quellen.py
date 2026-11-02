"""Rohdaten holen: ODL des BfS (WFS, Datenlizenz Deutschland – Namensnennung – 2.0) und Niederschlag/Schneehöhe
des DWD (Open Data, CC BY 4.0).

Jede Antwort wird zuerst unverändert auf die Platte geschrieben (JSON gzip-komprimiert, ZIP wie geliefert), mit
URL, SHA-256 und Abrufzeit im Manifest. Ausgewertet wird danach nur aus diesen Dateien; ein zweiter Lauf liest
dieselben Bytes und kommt zu denselben Zahlen. Bereits vorhandene Dateien werden nicht noch einmal geholt.
"""

from __future__ import annotations

import concurrent.futures as cf
import gzip
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import einlesen, geo

BFS_WFS = "https://www.imis.bfs.de/ogc/opendata/ows"
DWD = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate"
DWD_STUNDE = f"{DWD}/hourly/precipitation/recent"
DWD_TAG = f"{DWD}/daily/more_precip/recent"
USER_AGENT = "odlscan/0.1 (+https://github.com/panoherbe/odlscan)"
MAX_ABSTAND_KM = 20.0  # nächste DWD-Station höchstens so weit von der Sonde


def jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bfs_url(layer: str, kenn: str | None = None) -> str:
    p = {"service": "WFS", "version": "1.1.0", "request": "GetFeature", "typeName": f"opendata:{layer}",
         "outputFormat": "application/json"}
    if kenn:
        p["viewparams"] = f"kenn:{kenn}"
    return BFS_WFS + "?" + urllib.parse.urlencode(p)


def hole(url: str, timeout: float = 180, versuche: int = 4) -> bytes:
    letzter: Exception | None = None
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            letzter = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            letzter = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url}: {letzter}")


class Archiv:
    """Rohablage unter <wurzel>/raw/<abrufdatum>/ mit manifest.jsonl."""

    def __init__(self, wurzel: Path, abrufdatum: str):
        self.dir = wurzel / "raw" / abrufdatum
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.jsonl"
        self._lock = threading.Lock()

    def pfad(self, rel: str) -> Path:
        return self.dir / rel

    def ablegen(self, rel: str, url: str, daten: bytes) -> Path:
        ziel = self.dir / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_name(ziel.name + ".part")
        tmp.write_bytes(gzip.compress(daten) if rel.endswith(".gz") else daten)
        tmp.replace(ziel)
        satz = {"datei": rel, "url": url, "sha256": hashlib.sha256(daten).hexdigest(), "bytes": len(daten),
                "abgerufen": jetzt()}
        with self._lock, open(self.manifest, "a", encoding="utf-8") as f:
            f.write(json.dumps(satz, ensure_ascii=False) + "\n")
        return ziel

    def holen(self, rel: str, url: str) -> Path | None:
        ziel = self.dir / rel
        if ziel.exists():
            return ziel
        try:
            return self.ablegen(rel, url, hole(url))
        except urllib.error.HTTPError as e:
            with self._lock, open(self.dir / "fehler.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"datei": rel, "url": url, "http": e.code, "zeit": jetzt()}) + "\n")
            return None


def _parallel(aufgaben: list[tuple[str, str]], archiv: Archiv, arbeiter: int, name: str) -> int:
    ok, start = 0, time.time()
    with cf.ThreadPoolExecutor(max_workers=arbeiter) as ex:
        futs = [ex.submit(archiv.holen, rel, url) for rel, url in aufgaben]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            if fut.result() is not None:
                ok += 1
            if i % 200 == 0 or i == len(futs):
                print(f"  {name}: {i}/{len(futs)} ({time.time() - start:.0f} s)", flush=True)
    return ok


def dwd_zips(listing: bytes, muster: str) -> dict[int, str]:
    """Stations-ID -> Dateiname aus einem DWD-Verzeichnis-Listing."""
    namen = re.findall(rf'href="({muster})"', listing.decode("latin-1"))
    return {int(re.search(r"_(\d{5})_", n).group(1)): n for n in namen}


def naechste_dwd(sonden: list[dict], stationen: list[dict], vorhanden: dict[int, str]) -> dict[str, int]:
    """Je Sonde (kenn) die nächste DWD-Station mit Datei, höchstens MAX_ABSTAND_KM entfernt."""
    kand = [s for s in stationen if s["id"] in vorhanden]
    if not kand:
        return {}
    d = geo.abstand_km([s["lat"] for s in sonden], [s["lon"] for s in sonden],
                       [s["lat"] for s in kand], [s["lon"] for s in kand])
    zuordnung = {}
    for i, s in enumerate(sonden):
        j = int(d[i].argmin())
        if d[i, j] <= MAX_ABSTAND_KM:
            zuordnung[s["kenn"]] = kand[j]["id"]
    return zuordnung


def holen(wurzel: Path, abrufdatum: str | None = None, arbeiter: int = 4, max_sonden: int | None = None) -> Path:
    abrufdatum = abrufdatum or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    a = Archiv(wurzel, abrufdatum)
    print(f"Rohablage {a.dir}", flush=True)

    a.holen("bfs/odlinfo_sitelist.json.gz", bfs_url("odlinfo_sitelist"))
    sonden = [s for s in einlesen.sonden(a.pfad("bfs/odlinfo_sitelist.json.gz")) if s["status"] == 1]
    if max_sonden:
        sonden = sonden[:max_sonden]
    print(f"BfS: {len(sonden)} Sonden in Betrieb", flush=True)
    for layer in ("odlinfo_timeseries_odl_24h", "odlinfo_timeseries_odl_1h"):
        aufg = [(f"bfs/{layer}/{s['kenn']}.json.gz", bfs_url(layer, s["kenn"])) for s in sonden]
        n = _parallel(aufg, a, arbeiter, layer)
        print(f"BfS {layer}: {n}/{len(aufg)} Dateien", flush=True)

    for name, basis, beschreibung, muster in (
            ("stunde", DWD_STUNDE, "RR_Stundenwerte_Beschreibung_Stationen.txt", r"stundenwerte_RR_\d{5}_akt\.zip"),
            ("tag", DWD_TAG, "RR_Tageswerte_Beschreibung_Stationen.txt", r"tageswerte_RR_\d{5}_akt\.zip")):
        a.holen(f"dwd/{name}/index.html", basis + "/")
        a.holen(f"dwd/{name}/{beschreibung}", f"{basis}/{beschreibung}")
        vorhanden = dwd_zips(a.pfad(f"dwd/{name}/index.html").read_bytes(), muster)
        stationen = einlesen.dwd_stationen(a.pfad(f"dwd/{name}/{beschreibung}").read_bytes())
        zuordnung = naechste_dwd(sonden, stationen, vorhanden)
        a.ablegen(f"dwd/{name}/zuordnung.json", "lokal berechnet",
                  json.dumps(zuordnung, sort_keys=True).encode())
        ids = sorted(set(zuordnung.values()))
        aufg = [(f"dwd/{name}/{vorhanden[i]}", f"{basis}/{vorhanden[i]}") for i in ids]
        n = _parallel(aufg, a, arbeiter, f"DWD {name}")
        print(f"DWD {name}: {len(zuordnung)} Sonden mit Station ≤ {MAX_ABSTAND_KM:.0f} km, {n}/{len(ids)} Dateien",
              flush=True)
    return a.dir
