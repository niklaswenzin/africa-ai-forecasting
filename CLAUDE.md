# CLAUDE.md

Arbeitsanweisungen für Claude Code in diesem Repository.

## Projekt
Forecasting-Pipeline für afrikanische Wirtschafts- und Politikfragen: offene
Fragen von Polymarket und Metaculus laden, mit der Claude API und der OpenAI
API strukturierte Prognosen erzeugen, beide Modelle neben der Vergleichszahl
auf einer statischen Seite zeigen.

Der Umfang ist bewusst klein: drei Skripte, ein Lauf, eine Seite. Was hier
nicht steht, gehört nicht dazu — kein Zeitplan, keine Auswertung, kein Score.
Vor jeder Erweiterung fragen, ob sie diesen Rahmen sprengt.

## Arbeitsweise
- Änderungen in kleinen, abgeschlossenen Schritten, ein Skript pro Aufgabe.
- Funktionen statt Klassen, Lesbarkeit vor Eleganz, keine dichten Einzeiler.
- Jede Funktion mit Docstring, der Zweck und die nicht offensichtlichen
  Entscheidungen begründet.
- Vor grösseren Änderungen einen kurzen Plan zeigen und bestätigen lassen.

## Tech-Stack
- Python 3.10 oder neuer. Abhängigkeiten: requests und anthropic, weitere nur nach Rückfrage. Die OpenAI-Anbindung läuft bewusst über requests statt über das openai-Paket.
- Claude-Modell: claude-sonnet-5, als Konstante am Anfang von forecast.py. OpenAI-Modell: gpt-5.6-luna, als Konstante in forecaster_openai.py. Die Preisklassen sind seit dem Wechsel auf Sonnet 5 NICHT mehr gleich ($3/$15 gegen $1/$6) — das gehört in jede Auswertung.
- Achtung bei einem Claude-Modellwechsel, drei Stellen hängen an der Modellgeneration: das Web-Such-Tool (`web_search_20260209` für Sonnet 5 und neuer, `web_search_20250305` für Haiku 4.5), die Sampling-Parameter (Sonnet 5 lehnt `temperature` mit HTTP 400 ab, Haiku 4.5 verlangte es nicht, akzeptierte es aber), und `MAX_TOKENS` (deckelt Denken und Antwort gemeinsam). Vor jedem Wechsel an der API prüfen, nicht annehmen.
- Kein `temperature` mehr: beide Modelle lehnen Sampling-Parameter ab. Auf Haiku 4.5 war `temperature=0` gesetzt und hat messbar nichts stabilisiert (Ø 10.7 Punkte Bewegung zwischen zwei Läufen, mehr als beim OpenAI-Modell ohne jede Steuerung) — die Web-Suche liefert je Lauf andere Treffer, und das wirkt vor dem Sampling.
- Jede Prognose trägt die Modell-ID im Feld `model`. Nach einem Modellwechsel oder einem abgebrochenen Lauf stehen sonst Werte verschiedener Modelle unter demselben Schlüssel, ohne dass es erkennbar wäre.
- API-Keys über Umgebungsvariablen oder die lokale .env-Datei (durch .gitignore ausgeschlossen): ANTHROPIC_API_KEY, OPENAI_API_KEY, METACULUS_API_TOKEN. Nie im Code, nie in Commits.
- Polymarket Gamma API: Basis https://gamma-api.polymarket.com, öffentlich ohne Key. Verwendet wird `/markets/keyset`, nicht `/markets`: letzteres deckelt den Offset bei 2000 und liefert damit nur eine Stichprobe. Der Cursor-Parameter heisst `after_cursor`.
- Query-Parameter verifizieren, nicht raten — und zwar an der Quelle, die erreichbar ist: die API liefert ihre eigene OpenAPI-Beschreibung unter `/openapi.json`. docs.polymarket.com ist von diesem Anschluss aus gesperrt (siehe unten). Geratene Cursor-Namen quittiert die API NICHT mit einem Fehler, sie ignoriert sie und gibt stumm immer die erste Seite zurück — ohne Gegenprobe auf die zurückgegebenen IDs fällt das nicht auf.
- Netzsperre am Entwicklungsanschluss: der Provider (WWZ) biegt die DNS-Auflösung um, `kalshi.com`, `api.elections.kalshi.com` und `docs.polymarket.com` zeigen auf 212.4.64.206 mit einem Zertifikat für `*.wwz.ch`. `gamma-api.polymarket.com` wird durchgelassen. Kalshi ist von hier aus weder per API noch über die Website erreichbar — das ist keine Sache des Codes.

## Struktur
Drei Skripte in dieser Reihenfolge: `fetch_markets.py`, `forecast.py`, `build_site.py`.

- source_polymarket.py, source_metaculus.py: je eine Quelle. Jede stellt genau eine Funktion `lade_fragen()` bereit und liefert Einträge im gemeinsamen Format: id, source, question, market_p, benchmark_type, description, volume.
- fetch_markets.py: ruft alle Quellen in QUELLEN auf, filtert auf Afrika-Bezug, verwirft Sport-Fragen, wählt reihum über die Quellen maximal eine Frage pro Land, speichert markets.json.
- forecast.py: fragt pro Frage BEIDE Prognostiker und speichert forecasts.json. Claude über einen Messages-Call mit serverseitiger Web-Suche, OpenAI über forecaster_openai.py. System Prompt erzwingt reines JSON mit probability (0 bis 1), reasoning (maximal 3 Sätze, auf Englisch), confidence (low, medium, high). Antwort validieren, bei ungültigem JSON genau einmal erneut anfordern.
- forecaster_openai.py: zweiter Prognostiker über die OpenAI Responses API. Strukturierte Ausgabe liegt unter `text.format`, nicht unter `response_format`. Bekommt dasselbe Web-Such-Tool wie Claude, mit denselben gesperrten Domains — die frühere Verzerrung (nur Claude durfte suchen) war grösser als jeder gemessene Modellunterschied.
- pruefung.py: prüft Extremwerte (unter 2 Prozent, über 98) gegen die eigene Begründung. Widerspricht sie, wird genau einmal neu angefragt, danach bleibt der Wert stehen und die Karte trägt eine Warnung.
- build_site.py: baut aus markets.json und forecasts.json die Seite docs/index.html.
- snapshot.py: optional, hängt den Lauf an data/history/ an. Nichts auf der Seite hängt davon ab; die Aufnahmen existieren, damit eine spätere Auswertung Modell und Benchmark aus DERSELBEN Aufnahme bewerten kann.

## Mehrere Prognostiker
- forecasts.json führt die Schätzungen unter `forecasts` je Prognostiker-Schlüssel (`claude`, `openai`), nicht flach. Ein dritter kommt hinzu, ohne dass das Schema sich ändert.
- Die Reihenfolge steht in build_site.py (`PROGNOSTIKER`). Ein neuer Prognostiker braucht dort einen Eintrag und in `MODELL_FARBE` eine Farbe, sonst fehlt er in der Legende.
- Beide Modelle müssen dieselbe Aufgabe bekommen (gleiche Frage, gleiche Auflösungskriterien, gleiche Werkzeuge, keine Marktquote). Sonst vergleicht man Prompts statt Modelle.

## Mehrere Quellen
- Neue Quelle anbinden heisst: eine source_*.py schreiben und sie in QUELLEN eintragen. Filter, Länderregel und Auswahl gelten dann automatisch.
- IDs sind mit dem Quellennamen kombiniert (z. B. `polymarket-620335`), damit sie über Quellen hinweg eindeutig bleiben.
- benchmark_type unterscheidet `market_price` (echter Geldmarkt: Polymarket) von `community_forecast` (Metaculus-Median ohne Geldeinsatz). Die beiden dürfen auf der Seite nicht als dasselbe dargestellt werden.
- Der Metaculus-Median ist für unsere Zugriffsstufe gesperrt und kommt als `None`. Solche Fragen bleiben trotzdem drin — die Karte zeigt dann nur die beiden Modelle. Nie einen Ersatzwert raten.
- Endpoints und Query-Parameter jeder neuen Quelle vorher in deren offizieller Doku verifizieren, nicht raten.
- Preise normalisieren: market_p ist immer 0 bis 1.

## Methodische Leitplanke
Die Vergleichszahl darf nie in den Prompt von forecast.py gelangen. Sie
erscheint ausschliesslich auf der fertigen Seite. Andernfalls repliziert das
Modell die Marktmeinung, statt eine unabhängige Schätzung abzugeben, und der
Vergleich verliert seine Aussagekraft. Aus demselben Grund sind die
Prognosemarkt-Domains im Web-Such-Tool BEIDER Modelle gesperrt.

## Seite
- Farbe bedeutet WER, nicht WAS: Benchmark, Claude und GPT haben je eine feste Farbe, die in Zahl, Skalenpunkt und Begründung wiederkehrt. Kategorien tragen darum nur eine getönte Pille.
- Keine Flaggen-Emoji: Windows zeigt dafür das nackte Buchstabenpaar des Ländercodes.
- Fehlt eine Zahl, steht ein ruhiger Hinweis statt einer Null — nie eine Abweichung ohne Gegenwert, nie ein Balken auf 0 Prozent.

## Konventionen
- HTTP-Status prüfen, bei Fehlern klare Meldung und Abbruch, kein stilles Weiterlaufen.
- Sprache Deutsch, Schweizer Schreibweise (ss statt ß). In Markdown mit Umlauten, in Python-Code und Commit-Messages ohne (ae, oe, ue).
- Nach jedem abgeschlossenen Schritt ein Commit mit kurzer, präziser Message.
