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

def baue_markt_map(markets):
    """Macht aus der Markets-Liste ein Dict id -> Markt fuer schnelle Suche.

    Frueher haben wir hier nur die Quote abgelegt. Seit es mehrere Quellen
    gibt, brauchen wir auch source und benchmark_type, darum merken wir uns
    den ganzen Eintrag.
    """
    nach_id = {}
    for markt in markets:
        nach_id[markt["id"]] = markt
    return nach_id


def baue_zeilen(forecasts, nach_id):
    """Baut pro Prognose eine Ergebniszeile.

    Spalten: question, source, benchmark_type, model_p, market_p, diff.
    source und benchmark_type stehen mit dabei, weil ein Polymarket-Preis und
    ein Metaculus-Community-Median nicht dasselbe sind und eine spaetere
    Auswertung sie trennen koennen muss.
    """
    zeilen = []
    for prognose in forecasts:
        model_p = prognose["probability"]
        markt = nach_id.get(prognose["id"])  # ueber die id zuordnen
        market_p = markt.get("market_p") if markt else None

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
            "source": markt.get("source", "unknown") if markt else "unknown",
            "benchmark_type": markt.get("benchmark_type", "") if markt else "",
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
    spalten = ["question", "source", "benchmark_type", "model_p", "market_p", "diff"]
    try:
        with open(RESULTS_DATEI, "w", newline="", encoding="utf-8") as datei:
            writer = csv.DictWriter(datei, fieldnames=spalten)
            writer.writeheader()
            writer.writerows(zeilen)
    except PermissionError:
        # Unter Windows tritt das auf, wenn results.csv gerade in Excel o. Ae.
        # geoeffnet ist. Klare Meldung statt Traceback, dann abbrechen.
        print(
            f"Fehler: {RESULTS_DATEI} kann nicht geschrieben werden. "
            f"Ist die Datei gerade in Excel geoeffnet? Bitte schliessen und "
            f"erneut ausfuehren.",
            file=sys.stderr,
        )
        sys.exit(1)


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_json(MARKETS_DATEI)
    forecasts = lade_json(FORECASTS_DATEI)

    nach_id = baue_markt_map(markets)
    zeilen = baue_zeilen(forecasts, nach_id)

    schreibe_csv(zeilen)
    print(f"{len(zeilen)} Zeilen in {RESULTS_DATEI} geschrieben.")

    # Kurze Uebersicht auf der Konsole.
    for z in zeilen:
        print(f"  [{z['source']}] model={z['model_p']}  markt={z['market_p']}  "
              f"diff={z['diff']}  {z['question']}")


if __name__ == "__main__":
    main()
