"""source_metaculus.py

Quelle Metaculus - NOCH NICHT IMPLEMENTIERT.

lade_fragen() gibt bewusst eine leere Liste zurueck. Die Pipeline laeuft
dadurch unveraendert weiter, nur eben ohne Metaculus-Fragen. Sobald die
offene Punkte unten geklaert sind, wird hier die echte Abfrage ergaenzt.

Wichtiger Unterschied zu Polymarket und Kalshi
----------------------------------------------
Metaculus ist kein Wettmarkt. Es gibt keinen Preis, sondern den Median der
Community-Prognosen. Diese Zahl entsteht ohne Geldeinsatz und ist damit ein
anderer Benchmark als ein Marktpreis. Darum traegt jeder Eintrag von hier
benchmark_type "community_forecast" statt "market_price", und das Dashboard
beschriftet die Zahl entsprechend.

Offene Punkte vor der Implementierung
-------------------------------------
- Basis-URL und Endpoint in der offiziellen Doku verifizieren, nicht raten
  (CLAUDE.md). Startpunkt: https://www.metaculus.com/api/
- Braucht es einen API-Key fuer den Lesezugriff, oder reicht anonym?
- Welches Feld ist der Community-Median, und liegt er als 0..1 oder in Prozent
  vor? Muss auf 0..1 normalisiert werden, damit market_p vergleichbar bleibt.
- Wie filtert man auf offene Fragen, und wie auf binaere Ja/Nein-Fragen?
  Metaculus kennt auch numerische Fragen und Datumsfragen, die hier nicht
  passen und aussortiert werden muessen.
- Wo stehen die Aufloesungskriterien (fuer das Feld description)?
- Gibt es eine sinnvolle Entsprechung zum Volumen, um die Auswahl zu
  sortieren? Denkbar waere die Zahl der Prognostiker. Fehlt eine solche
  Groesse, muss fetch_markets.py die Quelle anders gewichten.
"""

QUELLE = "metaculus"


def lade_fragen():
    """Gibt vorerst eine leere Liste zurueck (Quelle noch nicht angebunden).

    Sobald implementiert, muss diese Funktion dasselbe Format liefern wie
    source_polymarket.lade_fragen(): eine Liste von Dicts mit den Schluesseln
    id, source, question, market_p, benchmark_type, description, volume.

    Konkret fuer diese Quelle:
      id             -> f"{QUELLE}-{frage_id}"
      source         -> QUELLE
      market_p       -> Community-Median, auf 0..1 normalisiert
      benchmark_type -> "community_forecast"
    """
    print(f"  {QUELLE}: noch nicht angebunden, 0 Fragen.")
    return []
