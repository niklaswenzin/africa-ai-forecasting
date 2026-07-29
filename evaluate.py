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

# Die Prognostiker in fester Reihenfolge. Sie bestimmt die Spaltenreihenfolge
# in results.csv; ein dritter kaeme hier dazu, ohne dass sonst etwas
# angefasst werden muss.
PROGNOSTIKER = ("claude", "openai")


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
    """Baut pro Frage eine Ergebniszeile mit beiden Modellen.

    Spalten: question, source, benchmark_type, market_p, dann je Modell die
    Schaetzung und ihre Abweichung zum Benchmark. Ein Modell ohne Prognose
    laesst seine beiden Spalten leer, statt die Zeile zu verwerfen - sonst
    verschwindet eine Frage aus der Auswertung, nur weil ein Modell aussetzte.

    source und benchmark_type stehen mit dabei, weil ein Polymarket-Preis und
    ein Metaculus-Community-Median nicht dasselbe sind und eine spaetere
    Auswertung sie trennen koennen muss.
    """
    zeilen = []
    for prognose in forecasts:
        markt = nach_id.get(prognose["id"])  # ueber die id zuordnen
        market_p = markt.get("market_p") if markt else None

        if market_p is None:
            print(
                f"Hinweis: keine Vergleichszahl fuer id {prognose['id']}, "
                f"die diff-Spalten bleiben leer.",
                file=sys.stderr,
            )

        zeile = {
            "question": prognose["question"],
            "source": markt.get("source", "unknown") if markt else "unknown",
            "benchmark_type": markt.get("benchmark_type", "") if markt else "",
            "market_p": market_p,
        }

        for name in PROGNOSTIKER:
            eintrag = (prognose.get("forecasts") or {}).get(name)
            model_p = eintrag["probability"] if eintrag else None

            if model_p is None or market_p is None:
                diff = None
            else:
                # Positiv = Modell schaetzt hoeher als der Benchmark.
                diff = round(model_p - market_p, 4)

            zeile[f"{name}_p"] = model_p
            zeile[f"{name}_diff"] = diff

        zeilen.append(zeile)
    return zeilen


# --- CSV schreiben ---------------------------------------------------------

def schreibe_csv(zeilen):
    """Schreibt die Zeilen als results.csv.

    newline="" ist unter Windows wichtig, sonst schreibt der csv-Writer
    zusaetzliche Leerzeilen zwischen die Datensaetze.
    """
    spalten = ["question", "source", "benchmark_type", "market_p"]
    for name in PROGNOSTIKER:
        spalten.extend([f"{name}_p", f"{name}_diff"])
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

    # Kurze Uebersicht auf der Konsole: Benchmark, dann beide Modelle.
    for z in zeilen:
        modelle = "  ".join(f"{name}={z[f'{name}_p']}" for name in PROGNOSTIKER)
        print(f"  [{z['source']}] benchmark={z['market_p']}  {modelle}  "
              f"{z['question'][:52]}")


if __name__ == "__main__":
    main()
