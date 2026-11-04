# Testprotokoll odlscan 0.2.0, 03.11.2026

Verfasser: Panagiotis Herbe. Alle Zahlen sind gemessen; Annahmen sind als solche bezeichnet. Dieser Lauf wertet
dieselbe Rohablage aus wie der Lauf vom 02.11.2026 (`nachweis/2026-11-02/`, odlscan 0.1.0) und ersetzt dessen
Bericht; was korrigiert wurde, steht in Abschnitt 8 von `BERICHT.md`.

## Umgebung

| | |
|---|---|
| Linux | Server mit Ubuntu 24.04.5 LTS, Intel Core i7-11700B mit 8 Kernen und 16 Threads (`lscpu`, 04.11.2026), 62 GB Arbeitsspeicher, Grafikkarte NVIDIA GeForce RTX 3060 mit 12 GB (`nvidia-smi`, 03.11.2026; von odlscan nicht genutzt, die Auswertung läuft auf der CPU); Docker-Image `python:3.12-slim` (Python 3.12.13, NumPy 2.5.4, Matplotlib 3.11.2; beide Bibliotheken seit 0.2.0 im `Dockerfile` auf diese Versionen festgelegt) |
| Windows | Tests in GitHub Actions auf `windows-latest` (und `ubuntu-latest`), Python 3.11, 3.12 und 3.13, bei jedem Push: Workflow `.github/workflows/tests.yml`. Das ist ein CI-Lauf auf GitHubs Windows-Server, kein eigener Windows-Rechner. Für 0.2.0 grün: Lauf 41701987286 vom 03.11.2026 (Commit `790b771`), alle sechs Jobs, je 16 Tests (Abschnitt „Windows“ unten); für 0.1.0: Lauf 41533297955 vom 02.11.2026, je 13 Tests. |
| Daten | Rohablage `raw/2026-11-02/` vom 02.11.2026: BfS-WFS `https://www.imis.bfs.de/ogc/opendata/ows` (Datenlizenz Deutschland – Namensnennung – 2.0), DWD Open Data `https://opendata.dwd.de/climate_environment/CDC/` (CC BY 4.0) |

## Schritte und Ergebnisse

| Schritt | Ergebnis |
|---|---|
| `docker compose build`, dann `docker compose run --rm test` | **16 Tests grün** in 0,16 s (13 aus 0.1.0, neu: Einordnung der Voralarme nach Regenmesser, Auswahl der Korrelations-Nachbarn, unveränderte Zufallsfolge mit Vergleichsvariante) |
| `docker compose run --rm odlscan auswerten --raw /daten/raw/2026-11-02 --aus /nachweis/2026-11-03` (03.11.2026, 16:17 UTC) | rund 31 s (Summe der Schritte 30,5 s, davon Einlesen 25 s); Ergebnis `BERICHT.md`, `ergebnisse.json`, `ereignisse_stunden.csv` (1.086 Ereignisse), `voralarme_stunden.csv` (25 Voralarme), `sprungkandidaten.csv` (317 Kandidaten), fünf Abbildungen mit 300 dpi |
| Rohablage, gezählt aus `manifest.jsonl` | 5.297 Einträge: **5.295 Abrufe** (3.121 BfS, 2.174 DWD) und 2 lokal berechnete Zuordnungsdateien; 389 MB wie geliefert, 73 MB Dateigröße in der Ablage (JSON gzip-komprimiert, ZIP wie geliefert), 84 MB belegter Plattenplatz (`du`); keine Fehlerdatei |
| Vergleich mit dem Lauf vom 02.11.2026 | Alle Werte der `ergebnisse.json` von 0.1.0 sind in 0.2.0 gleich (ausgenommen Version, Zeitstempel und Laufzeiten); neu sind nur zusätzliche Felder. `ereignisse_stunden.csv` und `sprungkandidaten.csv` sind Byte für Byte gleich, das Manifest inhaltlich gleich |

Der Bericht `BERICHT.pdf` ist aus `BERICHT.md` gerendert, mit diesem Protokoll als Anhang (Markdown → HTML → PDF, Abbildungen eingebettet).

## Neu gemessen in 0.2.0

| Was | Ergebnis |
|---|---|
| Regenmesser-Abdeckung der Erhöhungen | mit Messerdaten im Fenster: 842 von 842 „regen“, 23 von 139 „regional“, 10 von 20 „lokal“; 81 der 126 Erhöhungen ohne Messerdaten fallen auf den 02.11.2026: Die stündliche DWD-Reihe `recent` endet in der Ablage mit der Stunde 01.11.2026, 23 UTC, die ODL-Stundenwerte mit 02.11.2026, 21 UTC |
| Voralarme nach Regenmesser | 25 Voralarme: 13 Regen an der Mehrheit der beteiligten Sonden und Stunden, 3 gemessen trocken, 0 gemischt, 9 ohne Messerdaten an der Mehrheit (alle zwischen 01.11.2026, 23 UTC, und 02.11.2026, 21 UTC) |

## Verworfene Varianten (negative Befunde)

| Variante | Ergebnis | Entscheidung |
|---|---|---|
| Sprungstellen mit festem Strafterm 3 · σ² · ln n | 1.548 von 1.560 Sonden (Reihe allein) bzw. 1.521 (gegen Nachbarn) hätten mindestens einen Sprung; die Tagesreihen sind autokorreliert, σ aus Tagesdifferenzen unterschätzt die langsame Streuung | ersetzt durch Kalibrierung auf ein Alarmbudget von 10 % der Sonden (Annahme) |
| Referenz aus den fünf Nachbarn mit der höchsten Korrelation der Tagesänderungen (≤ 75 km, mindestens 200 gemeinsame Tage; 1.529 Sonden) statt Median aller Nachbarn ≤ 50 km, gleiches Alarmbudget | eingebaute Stufe 10 %: 218 von 240 erkannt (91 %) statt 231 von 240 (96 %); 5 %: 57 von 256 (22 %) statt 93 von 256 (36 %). Seit 0.2.0 im Code (`trend.referenz_korrelation`); das Protokoll vom 02.11.2026 nannte 78 % und 21 % aus einer nicht erhaltenen Umsetzung | verworfen; vermutlich prägen Rundung (0,001 µSv/h) und Zählrauschen die Tagesänderungen |
| Abklingverhältnis an der Spitze als Regenmerkmal | Median Regen 0,57, lokal 0,63: trennt mit Stundenwerten kaum; für reines Abklingen der Radon-Folgeprodukte erwartet man im Stundenmittel 0,35 bis 0,7, je nach Regenende in der Stunde (Bateman-Rechnung) | im Bericht als negativer Befund; braucht 10-Minuten-Werte |

## Was dieser Lauf nicht zeigt

Keine langfristigen Trends (ein Jahr Tageswerte), keine echten Plausibilisierungsentscheidungen (nicht öffentlich),
keine 10-Minuten-Werte, kein Radar-Niederschlag. Die Trefferquoten gelten für eingebaute Fehler.

## Windows (GitHub Actions)

Lauf https://github.com/panoherbe/odlscan/actions/runs/41701987286 (03.11.2026, 19:18–19:19 UTC, Commit `790b771`, Push
von odlscan 0.2.0): alle sechs Jobs erfolgreich. Unter `windows-latest` (`platform win32`): Python 3.11.9, 3.12.10 und
3.13.17, je **16 Tests grün** in 0,21–0,43 s; unter `ubuntu-latest` mit Python 3.11.17, 3.12.15 und 3.13.17 ebenso
(0,19–0,40 s). Getestet werden dort die Verfahren mit synthetischen Reihen und Beispieldateien im Format der Quellen,
ohne Netzzugriff; der vollständige Lauf auf den echten Daten (oben) lief unter Linux.
