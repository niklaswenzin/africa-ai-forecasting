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
- Python 3.10 oder neuer. Abhängigkeiten: requests und anthropic, weitere nur nach Rückfrage. Die OpenAI-Anbindung läuft bewusst über requests statt über das openai-Paket.
- Claude-Modell: claude-haiku-4-5, als Konstante am Anfang von forecast.py. OpenAI-Modell: gpt-5.6-luna, als Konstante in forecaster_openai.py. Beide bewusst in derselben Preisklasse (rund $1 Input je 1M Token) — sonst vergleicht man Preise statt Modelle.
- Achtung bei einem Claude-Modellwechsel: das Web-Such-Tool ist an die Modellgeneration gebunden. Haiku 4.5 braucht `web_search_20250305`, neuere Modelle `web_search_20260209`. Ein reiner Modell-Tausch ohne diese Zeile bricht die Pipeline.
- temperature=0 nur bei Claude. gpt-5.6-luna weist den Parameter mit HTTP 400 ab; die Prognosen dieses Modells sind darum weniger stabil. Diese Asymmetrie in jeder Auswertung erwähnen.
- API-Keys über Umgebungsvariablen oder die lokale .env-Datei (durch .gitignore ausgeschlossen): ANTHROPIC_API_KEY, OPENAI_API_KEY, METACULUS_API_TOKEN. Nie im Code, nie in Commits.
- Polymarket Gamma API: Basis https://gamma-api.polymarket.com, Endpoint /markets, öffentlich ohne Key. Query-Parameter vor der Implementierung in der offiziellen Doku (docs.polymarket.com) verifizieren, nicht raten.

## Struktur
- source_polymarket.py, source_metaculus.py, source_kalshi.py: je eine Quelle. Jede stellt genau eine Funktion `lade_fragen()` bereit und liefert Einträge im gemeinsamen Format: id, source, question, market_p, benchmark_type, description, volume. Metaculus und Kalshi sind noch nicht angebunden und geben eine leere Liste zurück.
- fetch_markets.py: ruft alle Quellen in QUELLEN auf, filtert auf Afrika-Bezug, verwirft Sport-Fragen, wählt reihum über die Quellen maximal eine Frage pro Land, speichert markets.json.
- forecast.py: fragt pro Frage BEIDE Prognostiker und speichert forecasts.json. Claude über einen Messages-Call mit optionaler serverseitiger Web-Suche, OpenAI über forecaster_openai.py. System Prompt erzwingt reines JSON mit probability (0 bis 1), reasoning (maximal 3 Sätze, auf Englisch), confidence (low, medium, high). Antwort validieren, bei ungültigem JSON genau einmal erneut anfordern.
- forecaster_openai.py: zweiter Prognostiker über die OpenAI Responses API. Strukturierte Ausgabe liegt unter `text.format`, nicht unter `response_format`. Bekommt bewusst kein Web-Such-Tool — diese Verzerrung gegenüber Claude gehört dokumentiert, solange sie besteht.
- evaluate.py: führt beide JSON-Dateien über die ID zusammen, schreibt results.csv mit question, source, benchmark_type, market_p und je Prognostiker zwei Spalten (`<name>_p`, `<name>_diff`).

## Mehrere Prognostiker
- forecasts.json führt die Schätzungen unter `forecasts` je Prognostiker-Schlüssel (`claude`, `openai`), nicht flach. Ein dritter kommt hinzu, ohne dass das Schema sich ändert.
- Die Reihenfolge steht in evaluate.py (`PROGNOSTIKER`) und build_site.py (`PROGNOSTIKER`) — beide Listen müssen zusammenpassen.
- Beide Modelle müssen dieselbe Aufgabe bekommen (gleiche Frage, gleiche Auflösungskriterien, keine Marktquote). Sonst vergleicht man Prompts statt Modelle.
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
