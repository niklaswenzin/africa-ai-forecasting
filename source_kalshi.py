"""source_kalshi.py

Quelle Kalshi - NOCH NICHT IMPLEMENTIERT.

lade_fragen() gibt bewusst eine leere Liste zurueck. Die Pipeline laeuft
dadurch unveraendert weiter, nur eben ohne Kalshi-Fragen. Sobald die offenen
Punkte unten geklaert sind, wird hier die echte Abfrage ergaenzt.

Kalshi ist wie Polymarket ein echter Geldmarkt, die Eintraege bekommen also
benchmark_type "market_price".

Erwartungshaltung
-----------------
Kalshi ist eine US-regulierte Boerse mit stark US-lastigem Angebot
(Wahlen, Wirtschaftsdaten, Wetter). Fragen mit Afrika-Bezug duerften dort
deutlich seltener sein als auf Polymarket. Gut moeglich, dass diese Quelle
am Ende nur ein bis zwei Fragen beitraegt oder zeitweise gar keine. Das ist
kein Fehler, sondern das erwartbare Ergebnis - fetch_markets.py meldet die
Luecke und fuellt sie nicht mit fachfremden Themen auf.

Offene Punkte vor der Implementierung
-------------------------------------
- Basis-URL und Endpoint in der offiziellen Doku verifizieren, nicht raten
  (CLAUDE.md). Startpunkt: https://docs.kalshi.com/
- Braucht der Markt-Endpoint eine Authentifizierung? Kalshi arbeitet fuer
  Teile der API mit Schluesselpaaren und signierten Requests. Falls ja: der
  Schluessel gehoert wie der Anthropic-Key in die Umgebung bzw. in die .env,
  nie in den Code, und zusaetzlich als Actions-Secret hinterlegt.
- Preise kommen bei Kalshi in Cent (0 bis 100). Vor dem Schreiben in market_p
  auf 0..1 teilen, sonst ist der Vergleich mit Polymarket falsch.
- Kalshi unterscheidet Events und Markets. Zu klaeren, welche Ebene der Frage
  in markets.json entspricht, und wie man Mehrfachnennungen zum selben Event
  vermeidet (analog zur Regel "maximal eine Frage pro Land").
- Feld fuer die Aufloesungskriterien (description) identifizieren.
- Welches Feld eignet sich als Volumen fuer die Sortierung der Auswahl?
"""

QUELLE = "kalshi"


def lade_fragen():
    """Gibt vorerst eine leere Liste zurueck (Quelle noch nicht angebunden).

    Sobald implementiert, muss diese Funktion dasselbe Format liefern wie
    source_polymarket.lade_fragen(): eine Liste von Dicts mit den Schluesseln
    id, source, question, market_p, benchmark_type, description, volume.

    Konkret fuer diese Quelle:
      id             -> f"{QUELLE}-{ticker}"
      source         -> QUELLE
      market_p       -> Ja-Preis, von Cent auf 0..1 umgerechnet
      benchmark_type -> "market_price"
    """
    print(f"  {QUELLE}: noch nicht angebunden, 0 Fragen.")
    return []
