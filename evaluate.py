"""evaluate.py

Fuehrt markets.json und forecasts.json ueber die id zusammen und schreibt
eine Vergleichstabelle results.csv mit den Spalten question, model_p,
market_p und diff.

Die Marktquote wird hier NUR zur Auswertung benutzt (nie zur Prognose).
"""

import csv
import json
import sys

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
RESULTS_DATEI = "results.csv"


# --- Daten laden -----------------------------------------------------------

def lade_json(pfad):
    """Liest eine JSON-Datei (UTF-8). Fehlt sie, brechen wir klar ab."""
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except FileNotFoundError:
        print(f"Fehler: Datei {pfad} nicht gefunden.", file=sys.stderr)
        sys.exit(1)


# --- Zuordnung -------------------------------------------------------------

def baue_quoten_map(markets):
    """Macht aus der Markets-Liste ein Dict id -> market_p fuer schnelle Suche."""
    quoten = {}
    for markt in markets:
        quoten[markt["id"]] = markt.get("market_p")
    return quoten


def baue_zeilen(forecasts, quoten):
    """Baut pro Prognose eine Ergebniszeile (question, model_p, market_p, diff)."""
    zeilen = []
    for prognose in forecasts:
        model_p = prognose["probability"]
        market_p = quoten.get(prognose["id"])  # ueber die id zuordnen

        if market_p is None:
            # Keine Marktquote vorhanden -> diff bleibt leer, wir melden es.
            print(
                f"Hinweis: keine Marktquote fuer id {prognose['id']}, "
                f"diff bleibt leer.",
                file=sys.stderr,
            )
            diff = None
        else:
            # Positiv = Modell schaetzt hoeher als der Markt.
            diff = round(model_p - market_p, 4)

        zeilen.append({
            "question": prognose["question"],
            "model_p": model_p,
            "market_p": market_p,
            "diff": diff,
        })
    return zeilen


# --- CSV schreiben ---------------------------------------------------------

def schreibe_csv(zeilen):
    """Schreibt die Zeilen als results.csv.

    newline="" ist unter Windows wichtig, sonst schreibt der csv-Writer
    zusaetzliche Leerzeilen zwischen die Datensaetze.
    """
    spalten = ["question", "model_p", "market_p", "diff"]
    with open(RESULTS_DATEI, "w", newline="", encoding="utf-8") as datei:
        writer = csv.DictWriter(datei, fieldnames=spalten)
        writer.writeheader()
        writer.writerows(zeilen)


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_json(MARKETS_DATEI)
    forecasts = lade_json(FORECASTS_DATEI)

    quoten = baue_quoten_map(markets)
    zeilen = baue_zeilen(forecasts, quoten)

    schreibe_csv(zeilen)
    print(f"{len(zeilen)} Zeilen in {RESULTS_DATEI} geschrieben.")

    # Kurze Uebersicht auf der Konsole.
    for z in zeilen:
        print(f"  model={z['model_p']}  markt={z['market_p']}  "
              f"diff={z['diff']}  {z['question']}")


if __name__ == "__main__":
    main()
