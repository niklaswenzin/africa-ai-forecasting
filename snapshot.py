"""snapshot.py

Schreibt den aktuellen Stand (Vergleichszahlen und Prognosen) als Zeitpunkt-
Aufnahme nach data/history/. Reines Anhaengen: eine Datei pro Lauf, nie
ueberschrieben, nie geloescht.

Warum das noetig ist
--------------------
markets.json und forecasts.json halten immer nur den JETZIGEN Stand. Ohne
Aufnahmen ist jeder frueherere Lauf unwiederbringlich weg, und damit auch die
Grundlage fuer alles, was danach kommen soll:

- Brier Score. Bewertet wird die Prognose gegen den Ausgang - und der Markt
  gegen SEINE Quote von damals, nicht gegen die kurz vor Aufloesung. Sonst
  gewinnt der Markt trivial, weil er am Ende gegen 0 oder 1 konvergiert. Das
  ist die Leakage-Falle, die im README steht.
- Zeitreihen auf der Seite (wie bewegt sich Markt gegen Modell).
- Die Frage, ob Prognosen ueber Laeufe stabil sind. Bisher liess sich das nur
  von Hand beobachten.

Was NICHT gespeichert wird
--------------------------
Die Begruendungstexte. Bei einem Marktabruf alle sechs Stunden waeren das
rund 1460 Dateien im Jahr mit je einem Absatz pro Modell und Frage - das Repo
liefe zu. Die Begruendung zum aktuellen Stand steht in forecasts.json; fuer
Auswertungen reichen Zahl, Konfidenz und Suchanzahl.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
HISTORIE_ORDNER = Path("data") / "history"

# Format der Version. Steht in jeder Datei, damit eine spaetere Auswertung
# aeltere Aufnahmen erkennt, statt an einem geaenderten Feld zu scheitern.
FORMAT_VERSION = 1


# --- Daten laden -----------------------------------------------------------

def lade_json(pfad):
    """Liest eine JSON-Datei (UTF-8). Fehlt sie, brechen wir klar ab."""
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except FileNotFoundError:
        print(f"Fehler: {pfad} nicht gefunden. Bitte zuerst fetch_markets.py "
              f"und forecast.py ausfuehren.", file=sys.stderr)
        sys.exit(1)


# --- Aufnahme bauen --------------------------------------------------------

def baue_zeitstempel():
    """Zeitstempel in UTC, als ISO-Text.

    Getrennt von baue_dateiname(), weil beide dasselbe Datum brauchen, aber in
    unterschiedlicher Schreibweise - und weil zwei getrennte Aufrufe von
    datetime.now() auseinanderlaufen koennten.
    """
    return datetime.now(timezone.utc)


def baue_dateiname(zeitpunkt):
    """Baut einen sortierbaren, dateisystemtauglichen Namen.

    Bewusst OHNE Doppelpunkte: die ISO-Schreibweise "13:45" waere unter
    Windows kein gueltiger Dateiname. Die Reihenfolge Jahr-Monat-Tag-Stunde
    sorgt dafuer, dass alphabetische Sortierung gleich chronologische ist.
    """
    return zeitpunkt.strftime("%Y-%m-%dT%H%MZ") + ".json"


def baue_eintrag(markt, prognose):
    """Baut die Aufnahme einer einzelnen Frage.

    question kommt mit, obwohl es sich nicht aendert: eine Aufnahme soll auch
    dann noch lesbar sein, wenn die Frage laengst aus markets.json gefallen
    ist - genau dann braucht man sie naemlich, naemlich bei der Auswertung
    aufgeloester Fragen.
    """
    modelle = {}
    for name, eintrag in ((prognose or {}).get("forecasts") or {}).items():
        modelle[name] = {
            "probability": eintrag.get("probability"),
            "confidence": eintrag.get("confidence", ""),
            "num_searches": eintrag.get("num_searches", 0),
        }

    return {
        "id": markt["id"],
        "source": markt.get("source", "unknown"),
        "question": markt.get("question", ""),
        "market_p": markt.get("market_p"),
        "benchmark_type": markt.get("benchmark_type", ""),
        "category": markt.get("category", ""),
        "country": markt.get("country", ""),
        "resolve_time": markt.get("resolve_time", ""),
        "forecasts": modelle,
    }


def baue_aufnahme(markets, forecasts, zeitpunkt):
    """Setzt die vollstaendige Aufnahme zusammen."""
    nach_id = {p["id"]: p for p in forecasts}

    return {
        "format_version": FORMAT_VERSION,
        "taken_at": zeitpunkt.isoformat().replace("+00:00", "Z"),
        "questions": [baue_eintrag(m, nach_id.get(m["id"])) for m in markets],
    }


# --- Vergleich mit der letzten Aufnahme ------------------------------------

def letzte_aufnahme():
    """Liest die neueste vorhandene Aufnahme, oder None.

    Die Dateinamen sortieren chronologisch, darum reicht das letzte Element.
    """
    if not HISTORIE_ORDNER.exists():
        return None

    dateien = sorted(HISTORIE_ORDNER.glob("*.json"))
    if not dateien:
        return None

    try:
        with open(dateien[-1], "r", encoding="utf-8") as datei:
            return json.load(datei)
    except (json.JSONDecodeError, OSError):
        # Eine beschaedigte Datei darf den Lauf nicht aufhalten; im Zweifel
        # schreiben wir lieber eine Aufnahme zu viel als eine zu wenig.
        return None


def hat_sich_geaendert(neu, alt):
    """True, wenn sich inhaltlich etwas geaendert hat.

    Verglichen wird alles ausser dem Zeitstempel - der ist per Definition
    immer neu. Ohne diese Pruefung entstuende bei jedem Lauf eine Datei, auch
    wenn sich weder eine Quote noch eine Prognose bewegt hat; die Historie
    liefe mit Duplikaten voll und die Action wuerde sinnlose Commits erzeugen.
    """
    if alt is None:
        return True
    return neu["questions"] != alt.get("questions")


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_json(MARKETS_DATEI)
    forecasts = lade_json(FORECASTS_DATEI)

    if not markets:
        print("Fehler: markets.json ist leer, es wird nichts aufgezeichnet.",
              file=sys.stderr)
        sys.exit(1)

    zeitpunkt = baue_zeitstempel()
    aufnahme = baue_aufnahme(markets, forecasts, zeitpunkt)

    if not hat_sich_geaendert(aufnahme, letzte_aufnahme()):
        print("Keine Aenderung gegenueber der letzten Aufnahme, "
              "nichts geschrieben.")
        return

    HISTORIE_ORDNER.mkdir(parents=True, exist_ok=True)
    ziel = HISTORIE_ORDNER / baue_dateiname(zeitpunkt)

    with open(ziel, "w", encoding="utf-8") as datei:
        json.dump(aufnahme, datei, ensure_ascii=False, indent=2)

    mit_prognose = sum(1 for f in aufnahme["questions"] if f["forecasts"])
    print(f"Aufnahme nach {ziel} geschrieben "
          f"({len(aufnahme['questions'])} Fragen, {mit_prognose} mit Prognose).")

    gesamt = len(list(HISTORIE_ORDNER.glob("*.json")))
    print(f"{gesamt} Aufnahme(n) in der Historie.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
