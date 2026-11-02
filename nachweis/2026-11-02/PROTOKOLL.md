# Testprotokoll odlscan 0.1.0, 02.11.2026

Verfasser: Panagiotis Herbe. Alle Zahlen sind gemessen; Annahmen sind als solche bezeichnet.

## Umgebung

| | |
|---|---|
| Linux | Server mit Ubuntu 24.04.5 LTS, 16 Kerne, 62 GB Arbeitsspeicher; Docker-Image `python:3.12-slim` (Python 3.12.13, NumPy 2.5.4, Matplotlib 3.11.2) |
| Windows | Tests in GitHub Actions auf `windows-latest` (und `ubuntu-latest`), Python 3.11, 3.12 und 3.13, bei jedem Push: Workflow `.github/workflows/tests.yml`. Das ist ein CI-Lauf auf GitHubs Windows-Server, kein eigener Windows-Rechner. Ergebnis siehe unten. |
| Daten | BfS-WFS `https://www.imis.bfs.de/ogc/opendata/ows` (Datenlizenz Deutschland – Namensnennung – 2.0), DWD Open Data `https://opendata.dwd.de/climate_environment/CDC/` (CC BY 4.0) |

## Schritte und Ergebnisse

| Schritt | Ergebnis |
|---|---|
| `docker compose run --rm test` | 13 Tests grün in 0,13 s |
| `odlscan holen --daten /daten --abrufdatum 2026-11-02` (02.11.2026, 21:33–21:47 UTC, 4 parallele Abrufe) | 1.560 Sonden in Betrieb; Tageswerte 1.560/1.560 Dateien in 521 s, Stundenwerte 1.560/1.560 in 108 s; DWD stündlicher Niederschlag 957 Stationen (für 1.550 Sonden ≤ 20 km) in 73 s, DWD Tageswerte 1.213 Stationen (für 1.557 Sonden) in 75 s; **5.297 Dateien, 84 MB, 0 Fehler**; Manifest mit URL, SHA-256, Bytes und Abrufzeit je Datei: `manifest.jsonl.gz` |
| `odlscan auswerten --raw /daten/raw/2026-11-02 --aus /nachweis/2026-11-02` | 32 s Gesamtlaufzeit, 43 MB Arbeitsspeicher; Ergebnis `BERICHT.md`, `ergebnisse.json`, `ereignisse_stunden.csv` (1.086 Ereignisse), `sprungkandidaten.csv` (317 Kandidaten), fünf Abbildungen |
| Wiederholung von `auswerten` auf derselben Rohablage | dieselben Zahlen (feste Zufallsstartwerte 1000–1004 und 2000–2004) |

Der Bericht `BERICHT.pdf` ist aus `BERICHT.md` gerendert (Markdown → HTML → PDF, Abbildungen eingebettet).

## Verworfene Varianten (negative Befunde, gemessen am 02.11.2026)

| Variante | Ergebnis | Entscheidung |
|---|---|---|
| Sprungstellen mit festem Strafterm 3 · σ² · ln n | 1.548 von 1.560 Sonden (Reihe allein) bzw. 1.521 (gegen Nachbarn) hätten mindestens einen Sprung; die Tagesreihen sind autokorreliert, σ aus Tagesdifferenzen unterschätzt die langsame Streuung | ersetzt durch Kalibrierung auf ein Alarmbudget von 10 % der Sonden (Annahme) |
| Referenz aus den fünf Nachbarn mit der höchsten Korrelation der Tagesänderungen (≤ 75 km) statt Median aller Nachbarn ≤ 50 km | eingebaute Stufe 10 %: 78 % statt 96 % erkannt; 5 %: 21 % statt 36 % | verworfen; die Tagesänderungen sind von Rundung (0,001 µSv/h) und Zählrauschen geprägt |
| Abklingverhältnis an der Spitze als Regenmerkmal | Median Regen 0,57, lokal 0,63: trennt mit Stundenwerten kaum | im Bericht als negativer Befund; braucht 10-Minuten-Werte |

## Was dieser Lauf nicht zeigt

Keine langfristigen Trends (ein Jahr Tageswerte), keine echten Plausibilisierungsentscheidungen (nicht öffentlich),
keine 10-Minuten-Werte, kein Radar-Niederschlag. Die Trefferquoten gelten für eingebaute Fehler.

## Windows (GitHub Actions)

Lauf https://github.com/panoherbe/odlscan/actions/runs/41533297955 (02.11.2026, 22:00 UTC, erster Push): alle sechs
Jobs erfolgreich. Unter `windows-latest` (`platform win32`): Python 3.11.9, 3.12.10 und 3.13.17, je **13 Tests
grün** in 0,22–0,23 s; unter `ubuntu-latest` mit Python 3.11–3.13 ebenso. Getestet werden dort die Verfahren mit
synthetischen Reihen und Beispieldateien im Format der Quellen, ohne Netzzugriff; der vollständige Lauf auf den
echten Daten (oben) lief unter Linux.
