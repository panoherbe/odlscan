# odlscan (Prototyp)

Trend- und Plausibilitätsanalyse auf den **offenen Daten des ODL-Messnetzes** des Bundesamts für Strahlenschutz
(Gamma-Ortsdosisleistung), mit Niederschlag und Schneehöhe des Deutschen Wetterdienstes. Reines Python
(NumPy, Matplotlib für Abbildungen), getestet unter Linux und Windows. Lizenz Apache 2.0.

*Prototype for trend and plausibility analysis of the open gamma dose rate data of Germany's Federal Office for
Radiation Protection (BfS). Documentation in German.*

## Was er kann

- **Rohdaten holen und unverändert ablegen:** Messstellenliste, Tageswerte (ein Jahr) und Stundenwerte (sieben
  Tage) aller Sonden in Betrieb über den WFS des BfS; DWD-Niederschlag (stündlich) und Schneehöhe (täglich) der
  nächsten Station im Umkreis von 20 km. Jede Antwort mit URL, SHA-256 und Abrufzeit in `manifest.jsonl`;
  ausgewertet wird nur aus der Ablage.
- **Plausibilitätsprüfung der Stundenwerte:** kausale Basislinie (Median 24 h), robuste Streuung, Erhöhung,
  Absenkung, Hänger; Einordnung einer Erhöhung als Regen (DWD-Messer), regional (Nachbarsonden) oder lokal
  (technisch prüfen); Abklingverhältnis an der Spitze (Radon-Folgeprodukte klingen in Stunden ab).
- **Voralarm-Regel nachgebildet:** zwei Sonden unter 30 km innerhalb einer Stunde erhöht; Anteil mit Regen.
- **Sprungstellen in Tageswerten:** binäre Segmentierung auf log(ODL), einmal auf der Reihe allein, einmal gegen
  den Median der Nachbarsonden (Homogenisierung); Schneetage ausgeblendet.
- **Schnee-Effekt:** Abweichung der Tages-ODL an Schneetagen gegenüber schneefreien Tagen derselben Sonde.
- **Güte gemessen statt behauptet:** künstliche Fehler (Spitze, Stufe, Drift, Absenkung, Hänger; Stufen 0,5–10 %
  in Tageswerten) in echte Reihen einbauen und wiederfinden: Trefferquote, Einordnung, Präzision.
- **Bericht:** `ergebnisse.json`, `BERICHT.md`, Abbildungen, Ereignis- und Kandidatenlisten als CSV.

## Start

```bash
pip install ".[plots]"
odlscan holen --daten daten                      # ca. 3.200 Abrufe beim BfS, ca. 1.500 beim DWD
odlscan auswerten --raw daten/raw/2026-11-02 --aus nachweis/2026-11-02
```

Mit Docker: `docker compose run --rm odlscan holen --daten /daten`, dann
`docker compose run --rm odlscan auswerten --raw /daten/raw/<Datum> --aus /nachweis/<Datum>`;
Tests: `docker compose run --rm test` oder `python -m pytest tests`.

## Nachweis

`nachweis/` enthält den gemessenen Lauf: Bericht (Markdown und PDF), Kennzahlen, Abbildungen, Testprotokoll.
Die Tests laufen bei jedem Push in GitHub Actions unter Ubuntu und Windows (Python 3.11 bis 3.13).

## Grenzen

Die öffentliche Schnittstelle liefert ein Jahr Tageswerte und sieben Tage Stundenwerte, nicht die vollständige
Messhistorie; die echten Plausibilisierungsentscheidungen des BfS sind nicht öffentlich. Der Prototyp zeigt
Verfahren und Messmethodik, keine abschließenden Aussagen zur radiologischen Lage.

## Daten und Lizenzen

- Bundesamt für Strahlenschutz (BfS), ODL-Messnetz: Datenlizenz Deutschland – Namensnennung – 2.0
  (Datenschnittstelle: https://odlinfo.bfs.de/ODL/DE/service/datenschnittstelle/datenschnittstelle_node.html)
- Deutscher Wetterdienst (DWD), Open Data: CC BY 4.0 (https://opendata.dwd.de/climate_environment/CDC/)

Die Rohdaten sind nicht Teil des Repositorys. Code: Apache 2.0 (`LICENSE`, `NOTICE`).
