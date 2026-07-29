"""brier.py

Rechnet den Brier Score fuer beide Modelle UND fuer den Benchmark, auf den
aufgeloesten Fragen. Ergebnis nach data/brier.json und auf die Konsole.

Der Brier Score ist der mittlere quadratische Fehler einer Wahrscheinlichkeit:
    (p - ausgang)^2, gemittelt ueber alle Fragen
Der Ausgang ist 1 oder 0. Kleiner ist besser. 0.25 ist das Ergebnis, das man
mit "immer 50 Prozent" erreicht - wer darueber liegt, ist schlechter als
konsequentes Achselzucken.

Die entscheidende Entscheidung: WANN wird gemessen
--------------------------------------------------
Modell und Benchmark werden aus DERSELBEN Aufnahme gelesen, naemlich der
fruehesten, in der eine Prognose zu dieser Frage steht. Beide haben damit
exakt denselben Informationsstand.

Das ist der ganze Grund, warum snapshot.py existiert. Wuerde man den Markt
gegen seine Quote kurz vor der Aufloesung messen, gewaenne er immer: ein Markt
konvergiert gegen 0 oder 1, sobald der Ausgang absehbar ist, und haette dann
einen fast perfekten Score gegen eine Modellprognose von Wochen vorher. Das
waere kein Vergleich, sondern ein Messfehler - genau die Leakage-Falle, die
im README steht.

Was nicht gezaehlt wird
-----------------------
- Fragen ohne bekannten Ausgang. Metaculus gibt ihn mit unserer Zugriffsstufe
  nicht her (siehe resolve_questions.py), diese Fragen fehlen darum.
- Fragen, zu denen es keine Aufnahme mit Prognose gibt.
- Fuer den Benchmark zusaetzlich: Fragen ohne Vergleichszahl in der
  betreffenden Aufnahme.

Ein Modell wird also nur an Fragen gemessen, die es auch prognostiziert hat.
Die Zahl der ausgewerteten Fragen (n) steht darum ueberall dabei - ein Score
ohne n ist wertlos.
"""

import json
import sys
from pathlib import Path

# --- Konstanten ------------------------------------------------------------

HISTORIE_ORDNER = Path("data") / "history"
RESOLVED_DATEI = Path("data") / "resolved.json"
BRIER_DATEI = Path("data") / "brier.json"

BENCHMARK_NAME = "benchmark"    # Markt bzw. Community-Median
STATUS_RESOLVED = "resolved"

# Referenzwert: der Score, den man mit einer konstanten Schaetzung von 0.5
# erreicht. Dient als Einordnung, nicht als Ziel.
MUENZWURF = 0.25


# --- Daten laden -----------------------------------------------------------

def lade_json(pfad, standard):
    """Liest eine JSON-Datei, oder gibt den Standardwert zurueck."""
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError):
        return standard


def lade_aufnahmen():
    """Liest alle Aufnahmen, aelteste zuerst.

    Die Dateinamen sind so gebaut, dass alphabetische Sortierung zugleich
    chronologische ist - siehe snapshot.py.
    """
    if not HISTORIE_ORDNER.exists():
        return []

    aufnahmen = []
    for datei in sorted(HISTORIE_ORDNER.glob("*.json")):
        aufnahme = lade_json(datei, None)
        if aufnahme is not None:
            aufnahmen.append(aufnahme)
    return aufnahmen


# --- Erste Prognose je Frage finden ---------------------------------------

def erste_prognosen(aufnahmen):
    """Sucht je Frage die FRUEHESTE Aufnahme, die eine Prognose enthaelt.

    Rueckgabe: Dict frage_id -> {taken_at, market_p, forecasts}. Aufnahmen
    ohne jede Prognose zu einer Frage werden uebersprungen: eine Karte, die
    nur die Marktquote kennt, taugt nicht als Messzeitpunkt, weil dann fuer
    das Modell nichts zu messen waere.

    Warum die frueheste und nicht die letzte: je frueher, desto weniger weiss
    der Markt bereits, und desto aussagekraeftiger ist der Vergleich. Die
    letzte waere die unfairste Wahl - siehe Modul-Docstring.
    """
    gefunden = {}

    for aufnahme in aufnahmen:                      # aelteste zuerst
        for eintrag in aufnahme.get("questions", []):
            frage_id = eintrag["id"]
            if frage_id in gefunden:
                continue                            # schon eine fruehere da
            if not eintrag.get("forecasts"):
                continue                            # noch keine Prognose

            gefunden[frage_id] = {
                "taken_at": aufnahme.get("taken_at", ""),
                "market_p": eintrag.get("market_p"),
                "forecasts": eintrag["forecasts"],
            }

    return gefunden


# --- Rechnen ---------------------------------------------------------------

def brier_einzeln(p, ausgang):
    """Quadratischer Fehler einer einzelnen Prognose."""
    return (p - ausgang) ** 2


def sammle_paare(aufgeloest, prognosen):
    """Bildet je Prognostiker die Liste (p, ausgang) fuer alle wertbaren Fragen.

    Der Benchmark wird wie ein weiterer Prognostiker behandelt - genau das
    ist der Sinn der Uebung. Er bekommt aber NUR die Fragen, bei denen zum
    Messzeitpunkt auch eine Vergleichszahl vorlag, sonst waere sein Score
    ueber einen anderen Fragensatz gerechnet als der der Modelle.
    """
    paare = {}
    details = []

    for eintrag in aufgeloest:
        if eintrag.get("status") != STATUS_RESOLVED:
            continue
        ausgang = eintrag.get("outcome")
        if ausgang not in (0, 1):
            continue

        gemessen = prognosen.get(eintrag["id"])
        if gemessen is None:
            continue                                # nie mit Prognose gesehen

        zeile = {
            "id": eintrag["id"],
            "question": eintrag.get("question", ""),
            "outcome": ausgang,
            "measured_at": gemessen["taken_at"],
            "scores": {},
        }

        for name, prognose in gemessen["forecasts"].items():
            p = prognose.get("probability")
            if p is None:
                continue
            paare.setdefault(name, []).append((p, ausgang))
            zeile["scores"][name] = {"p": p, "brier": round(brier_einzeln(p, ausgang), 4)}

        market_p = gemessen.get("market_p")
        if market_p is not None:
            paare.setdefault(BENCHMARK_NAME, []).append((market_p, ausgang))
            zeile["scores"][BENCHMARK_NAME] = {
                "p": market_p,
                "brier": round(brier_einzeln(market_p, ausgang), 4),
            }

        details.append(zeile)

    return paare, details


def werte_aus(paare):
    """Rechnet je Prognostiker Score, Anzahl und mittlere Schaetzung."""
    ergebnis = {}
    for name, liste in paare.items():
        if not liste:
            continue
        scores = [brier_einzeln(p, a) for p, a in liste]
        ergebnis[name] = {
            "brier": round(sum(scores) / len(scores), 4),
            "n": len(liste),
            "mean_forecast": round(sum(p for p, _ in liste) / len(liste), 4),
            "base_rate": round(sum(a for _, a in liste) / len(liste), 4),
        }
    return ergebnis


# --- Ausgabe ---------------------------------------------------------------

def zeige(ergebnis, anzahl_aufgeloest, anzahl_bewertbar):
    """Gibt die Auswertung lesbar aus, mit den noetigen Vorbehalten."""
    print(f"{anzahl_aufgeloest} Frage(n) mit bekanntem Ausgang, "
          f"davon {anzahl_bewertbar} mit einer Prognose zum Messzeitpunkt.")

    if not ergebnis:
        print("\nNoch kein Brier Score berechenbar.")
        print("Das ist erwartbar, solange keine der Fragen aufgeloest ist -")
        print("die naechsten Kandidaten sind die Wahlen in Guinea-Bissau und Sambia.")
        return

    print(f"\n{'Prognostiker':14s} {'Brier':>7s} {'n':>4s} {'Ø p':>7s} {'Basisrate':>10s}")
    for name, w in sorted(ergebnis.items(), key=lambda x: x[1]["brier"]):
        print(f"{name:14s} {w['brier']:7.4f} {w['n']:4d} "
              f"{w['mean_forecast']:7.3f} {w['base_rate']:10.3f}")

    print(f"\nZum Vergleich: konstant 0.5 zu schaetzen ergaebe {MUENZWURF}.")

    kleinste = min(w["n"] for w in ergebnis.values())
    if kleinste < 20:
        print(f"ACHTUNG: nur {kleinste} bewertete Frage(n) beim kleinsten "
              f"Prognostiker. Bei so wenigen Fragen ist ein Rangunterschied "
              f"Zufall und keine Aussage.")


# --- Hauptablauf -----------------------------------------------------------

def main():
    aufgeloest = lade_json(RESOLVED_DATEI, [])
    if not aufgeloest:
        print(f"Fehler: {RESOLVED_DATEI} fehlt oder ist leer. Bitte zuerst "
              f"resolve_questions.py ausfuehren.", file=sys.stderr)
        sys.exit(1)

    aufnahmen = lade_aufnahmen()
    if not aufnahmen:
        print("Fehler: keine Aufnahmen unter data/history/. Bitte zuerst "
              "snapshot.py ausfuehren.", file=sys.stderr)
        sys.exit(1)

    prognosen = erste_prognosen(aufnahmen)
    paare, details = sammle_paare(aufgeloest, prognosen)
    ergebnis = werte_aus(paare)

    mit_ausgang = sum(1 for e in aufgeloest if e.get("status") == STATUS_RESOLVED
                      and e.get("outcome") in (0, 1))
    zeige(ergebnis, mit_ausgang, len(details))

    BRIER_DATEI.parent.mkdir(parents=True, exist_ok=True)
    with open(BRIER_DATEI, "w", encoding="utf-8") as datei:
        json.dump({
            "scores": ergebnis,
            "n_resolved": mit_ausgang,
            "n_scored": len(details),
            "snapshots": len(aufnahmen),
            # Die Methode steht in der Datei selbst, damit eine spaetere
            # Auswertung nicht raten muss, wogegen gemessen wurde.
            "method": ("Modell und Benchmark werden aus derselben Aufnahme "
                       "gelesen: der fruehesten mit einer Prognose zur Frage."),
            "questions": details,
        }, datei, ensure_ascii=False, indent=2)

    print(f"\nAuswertung nach {BRIER_DATEI} geschrieben.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
