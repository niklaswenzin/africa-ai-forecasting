# CLAUDE.md

Arbeitsanweisungen für Claude Code in diesem Repository.

## Projekt
Forecasting-Pipeline für afrikanische Wirtschafts- und Politikfragen: offene
Fragen von Polymarket laden, mit der Claude API strukturierte Prognosen
erzeugen, das Modell gegen die Marktquote auswerten.

## Arbeitsweise
- Änderungen in kleinen, abgeschlossenen Schritten, ein Skript pro Aufgabe.
- Funktionen statt Klassen, Lesbarkeit vor Eleganz, keine dichten Einzeiler.
- Jede Funktion mit Docstring, der Zweck und die nicht offensichtlichen
  Entscheidungen begründet.
- Vor grösseren Änderungen einen kurzen Plan zeigen und bestätigen lassen.

## Tech-Stack
- Python 3.10 oder neuer. Abhängigkeiten: requests und anthropic, weitere nur nach Rückfrage.
- Claude-Modell: claude-sonnet-4-6, als Konstante am Anfang von forecast.py.
- API-Key über die Umgebungsvariable ANTHROPIC_API_KEY oder eine lokale .env-Datei (durch .gitignore ausgeschlossen). Nie im Code, nie in Commits.
- Polymarket Gamma API: Basis https://gamma-api.polymarket.com, Endpoint /markets, öffentlich ohne Key. Query-Parameter vor der Implementierung in der offiziellen Doku (docs.polymarket.com) verifizieren, nicht raten.

## Struktur
- source_polymarket.py, source_metaculus.py, source_kalshi.py: je eine Quelle. Jede stellt genau eine Funktion `lade_fragen()` bereit und liefert Einträge im gemeinsamen Format: id, source, question, market_p, benchmark_type, description, volume. Metaculus und Kalshi sind noch nicht angebunden und geben eine leere Liste zurück.
- fetch_markets.py: ruft alle Quellen in QUELLEN auf, filtert auf Afrika-Bezug, verwirft Sport-Fragen, wählt reihum über die Quellen maximal eine Frage pro Land, speichert markets.json.
- forecast.py: pro Frage ein Messages-Call, optional mit serverseitiger Web-Suche. System Prompt erzwingt reines JSON mit probability (0 bis 1), reasoning (maximal 3 Sätze, auf Englisch), confidence (low, medium, high). Antwort validieren, bei ungültigem JSON genau einmal erneut anfordern. Speichert forecasts.json.
- evaluate.py: führt beide JSON-Dateien über die ID zusammen, schreibt results.csv mit question, source, benchmark_type, model_p, market_p, diff.
- build_site.py: baut aus beiden JSON-Dateien die statische Seite docs/index.html.

## Mehrere Quellen
- Neue Quelle anbinden heisst: eine source_*.py schreiben und sie in QUELLEN eintragen. Filter, Länderregel und Auswahl gelten dann automatisch.
- IDs sind mit dem Quellennamen kombiniert (z. B. `polymarket-620335`), damit sie über Quellen hinweg eindeutig bleiben.
- benchmark_type unterscheidet `market_price` (echter Geldmarkt: Polymarket, Kalshi) von `community_forecast` (Metaculus-Median ohne Geldeinsatz). Die beiden dürfen in der Auswertung und auf der Seite nicht als dasselbe dargestellt werden.
- Endpoints und Query-Parameter jeder neuen Quelle vorher in deren offizieller Doku verifizieren, nicht raten. Die offenen Punkte stehen jeweils oben in der Platzhalter-Datei.
- Preise normalisieren: market_p ist immer 0 bis 1 (Kalshi liefert Cent, also durch 100 teilen).

## Methodische Leitplanke
Die Marktquote darf nie in den Prompt von forecast.py gelangen. Sie dient
ausschliesslich der Auswertung in evaluate.py. Andernfalls repliziert das
Modell die Marktmeinung, statt eine unabhängige Schätzung abzugeben, und der
Vergleich verliert seine Aussagekraft.

## Konventionen
- HTTP-Status prüfen, bei Fehlern klare Meldung und Abbruch, kein stilles Weiterlaufen.
- Sprache Deutsch, Schweizer Schreibweise (ss statt ß). In Markdown mit Umlauten, in Python-Code und Commit-Messages ohne (ae, oe, ue).
- Nach jedem abgeschlossenen Schritt ein Commit mit kurzer, präziser Message.
