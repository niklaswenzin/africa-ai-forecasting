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
- fetch_markets.py: lädt offene Fragen mit Afrika-Bezug, maximal eine pro Land, keine Sport-Fragen. Extrahiert Frage, ID, Auflösungskriterien und aktuelle Quote (outcomePrices), speichert markets.json.
- forecast.py: pro Frage ein Messages-Call, optional mit serverseitiger Web-Suche. System Prompt erzwingt reines JSON mit probability (0 bis 1), reasoning (maximal 3 Sätze), confidence (low, medium, high). Antwort validieren, bei ungültigem JSON genau einmal erneut anfordern. Speichert forecasts.json.
- evaluate.py: führt beide JSON-Dateien über die ID zusammen, schreibt results.csv mit question, model_p, market_p, diff.

## Methodische Leitplanke
Die Marktquote darf nie in den Prompt von forecast.py gelangen. Sie dient
ausschliesslich der Auswertung in evaluate.py. Andernfalls repliziert das
Modell die Marktmeinung, statt eine unabhängige Schätzung abzugeben, und der
Vergleich verliert seine Aussagekraft.

## Konventionen
- HTTP-Status prüfen, bei Fehlern klare Meldung und Abbruch, kein stilles Weiterlaufen.
- Sprache Deutsch, Schweizer Schreibweise (ss statt ß). In Markdown mit Umlauten, in Python-Code und Commit-Messages ohne (ae, oe, ue).
- Nach jedem abgeschlossenen Schritt ein Commit mit kurzer, präziser Message.
