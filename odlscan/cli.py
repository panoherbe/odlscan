"""Kommandozeile: odlscan holen | auswerten."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="odlscan", description="Trend- und Plausibilitätsanalyse auf offenen ODL-Daten")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="befehl", required=True)

    h = sub.add_parser("holen", help="Rohdaten von BfS und DWD unverändert ablegen")
    h.add_argument("--daten", type=Path, required=True, help="Datenordner (darin raw/<Abrufdatum>/)")
    h.add_argument("--abrufdatum", help="Name des Rohordners (Standard: heute, UTC)")
    h.add_argument("--arbeiter", type=int, default=4, help="gleichzeitige Abrufe (Standard 4)")
    h.add_argument("--max-sonden", type=int, help="nur die ersten N Sonden (zum Ausprobieren)")

    a = sub.add_parser("auswerten", help="Rohablage auswerten, Kennzahlen, Abbildungen und Bericht schreiben")
    a.add_argument("--raw", type=Path, required=True, help="Rohordner raw/<Abrufdatum>")
    a.add_argument("--aus", type=Path, required=True, help="Zielordner")
    a.add_argument("--durchlaeufe", type=int, default=5)
    a.add_argument("--je-lauf", type=int, default=300)
    a.add_argument("--ohne-abbildungen", action="store_true")

    args = ap.parse_args(argv)
    if args.befehl == "holen":
        from .quellen import holen
        holen(args.daten, args.abrufdatum, args.arbeiter, args.max_sonden)
    else:
        from .bericht import auswerten
        r = auswerten(args.raw, args.aus, args.durchlaeufe, args.je_lauf, not args.ohne_abbildungen)
        print(f"{r['daten']['sonden_in_betrieb']} Sonden ausgewertet, Bericht: {args.aus / 'BERICHT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
