"""resolve_questions.py

Prueft, welche Fragen inzwischen aufgeloest sind, und haelt den Ausgang in
data/resolved.json fest. Das ist die zweite Haelfte der Historie: die
Aufnahmen sagen, was wir wann prognostiziert haben, diese Datei sagt, was
tatsaechlich eingetreten ist. Erst beides zusammen ergibt einen Brier Score.

Warum die IDs aus der HISTORIE kommen, nicht aus markets.json
-------------------------------------------------------------
Sobald eine Frage aufgeloest ist, faellt sie aus markets.json heraus - genau
dann wollen wir sie aber auswerten. Wir sammeln die zu pruefenden IDs darum
aus allen Aufnahmen unter data/history/. Deshalb speichert snapshot.py auch
den Fragetext mit: er waere sonst mit der Aufloesung verloren.

Was verifiziert ist (2026-07-29)
--------------------------------
Polymarket:
- Einzelabruf ueber GET /markets/{id} liefert ein Objekt, auch fuer laengst
  geschlossene Maerkte. Die Listenabfrage mit closed=false wuerde sie nicht
  mehr enthalten.
- Der Ausgang steht in outcomePrices: ["1","0"] heisst Yes, ["0","1"] heisst
  No. Ueber 200 kuerzlich geschlossene Maerkte geprueft - 80 mal Yes, 120 mal
  No, kein mehrdeutiger Fall.
- Es gibt aber Altfaelle mit ["0","0"] (gesehen an einem annullierten Markt
  von 2020). Solche behandeln wir als "kein Ausgang", nicht als Nein - ein
  geratener Ausgang wuerde den Brier Score still verfaelschen.

Metaculus: BLOCKIERT
--------------------
Der Ausgang ist mit unserer Zugriffsstufe nicht lesbar. Bei allen geprueften
aufgeloesten Fragen ist question.resolution None, und question.
resolution_criteria ebenfalls - obwohl beide bei offenen Fragen belegt sind.
Das ist dieselbe Beschraenkung wie beim Community-Median (siehe
source_metaculus.py), kein leeres Feld.

Metaculus-Fragen bekommen darum den Status "unavailable" statt eines
geratenen Ausgangs. Sie zaehlen nicht in den Brier Score, und das ist richtig
so: eine Frage mit unbekanntem Ausgang als "Nein" zu werten waere schlimmer
als sie wegzulassen.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"
HISTORIE_ORDNER = Path("data") / "history"
RESOLVED_DATEI = Path("data") / "resolved.json"

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
HEADERS = {"User-Agent": "africa-ai-forecasting/1.0"}
TIMEOUT = 30
PAUSE = 0.3          # Sekunden zwischen Abfragen, um die API nicht zu fluten

# Status einer geprueften Frage.
#   resolved    - Ausgang bekannt, zaehlt in die Auswertung
#   open        - noch nicht aufgeloest, spaeter erneut pruefen
#   unavailable - Quelle gibt den Ausgang nicht her (Metaculus), nie wieder
#                 pruefen, aber sichtbar behalten
#   void        - geschlossen, aber ohne ablesbaren Ausgang (annulliert)
STATUS_RESOLVED = "resolved"
STATUS_OPEN = "open"
STATUS_UNAVAILABLE = "unavailable"
STATUS_VOID = "void"


# --- Bekannte Fragen sammeln ----------------------------------------------

def lade_json(pfad, standard):
    """Liest eine JSON-Datei, oder gibt den Standardwert zurueck.

    Fehlende Dateien sind hier der Normalfall (erster Lauf), kein Fehler.
    """
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError):
        return standard


def sammle_fragen():
    """Sammelt alle je gesehenen Fragen aus Historie und aktuellem Stand.

    Rueckgabe: Dict id -> {id, source, question}. Spaetere Aufnahmen
    ueberschreiben fruehere, das ist unkritisch, weil sich an diesen drei
    Feldern nichts aendert.
    """
    fragen = {}

    for datei in sorted(HISTORIE_ORDNER.glob("*.json")) if HISTORIE_ORDNER.exists() else []:
        aufnahme = lade_json(datei, {})
        for eintrag in aufnahme.get("questions", []):
            fragen[eintrag["id"]] = {
                "id": eintrag["id"],
                "source": eintrag.get("source", "unknown"),
                "question": eintrag.get("question", ""),
            }

    # Der aktuelle Stand kann Fragen enthalten, die noch in keiner Aufnahme
    # stehen (erster Lauf nach einem fetch).
    for markt in lade_json(MARKETS_DATEI, []):
        fragen[markt["id"]] = {
            "id": markt["id"],
            "source": markt.get("source", "unknown"),
            "question": markt.get("question", ""),
        }

    return fragen


# --- Polymarket abfragen ---------------------------------------------------

def rohe_id(zusammengesetzte_id):
    """Macht aus "polymarket-620335" wieder "620335".

    Die IDs sind seit der Mehrquellen-Umstellung mit dem Quellennamen
    kombiniert; die API kennt nur den hinteren Teil.
    """
    return zusammengesetzte_id.split("-", 1)[1]


def lies_ausgang(market):
    """Liest den Ausgang eines geschlossenen Markets: 1, 0, oder None.

    1 heisst, die Frage wurde mit Ja aufgeloest, 0 mit Nein. None heisst,
    dass sich kein Ausgang ablesen laesst - dann ist der Markt annulliert
    oder in einem Zustand, den wir nicht deuten koennen. Wir raten NICHT:
    ein falscher Ausgang verfaelscht jeden spaeteren Brier Score, ohne dass
    es auffaellt.
    """
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        preise = json.loads(market.get("outcomePrices") or "[]")
    except (json.JSONDecodeError, TypeError):
        return None

    if "Yes" not in outcomes or len(preise) != len(outcomes):
        return None

    index_yes = outcomes.index("Yes")
    try:
        p_yes = float(preise[index_yes])
    except (TypeError, ValueError):
        return None

    # Aufgeloeste Maerkte stehen exakt auf 1 oder 0. Alles dazwischen ist
    # kein Ausgang, sondern ein Zwischenstand oder eine Annullierung.
    if p_yes >= 0.99:
        return 1
    if p_yes <= 0.01 and any(float(x or 0) >= 0.99 for x in preise):
        return 0
    return None


def pruefe_polymarket(frage):
    """Fragt einen einzelnen Polymarket-Markt ab und deutet seinen Zustand.

    Rueckgabe: (status, ausgang_oder_None, zeitpunkt_oder_leer).
    """
    url = f"{GAMMA_URL}/{rohe_id(frage['id'])}"
    try:
        antwort = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.RequestException as fehler:
        print(f"  {frage['id']}: Abfrage fehlgeschlagen "
              f"({type(fehler).__name__}), bleibt offen.", file=sys.stderr)
        return STATUS_OPEN, None, ""

    if antwort.status_code != 200:
        print(f"  {frage['id']}: HTTP {antwort.status_code}, bleibt offen.",
              file=sys.stderr)
        return STATUS_OPEN, None, ""

    market = antwort.json()
    if not market.get("closed"):
        return STATUS_OPEN, None, ""

    ausgang = lies_ausgang(market)
    if ausgang is None:
        return STATUS_VOID, None, market.get("endDate", "")

    return STATUS_RESOLVED, ausgang, market.get("endDate", "")


# --- Hauptablauf -----------------------------------------------------------

def main():
    fragen = sammle_fragen()
    if not fragen:
        print("Keine bekannten Fragen. Bitte zuerst fetch_markets.py und "
              "snapshot.py ausfuehren.", file=sys.stderr)
        sys.exit(1)

    bekannt = {e["id"]: e for e in lade_json(RESOLVED_DATEI, [])}
    print(f"{len(fragen)} bekannte Fragen, {len(bekannt)} bereits geprueft.")

    jetzt = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    neu_aufgeloest = 0
    geprueft = 0

    for frage in fragen.values():
        vorher = bekannt.get(frage["id"])

        # Endzustaende nie erneut abfragen: ein aufgeloester Markt bleibt
        # aufgeloest, und eine Quelle, die den Ausgang nicht hergibt, wird ihn
        # auch beim naechsten Lauf nicht hergeben.
        if vorher and vorher["status"] in (STATUS_RESOLVED, STATUS_UNAVAILABLE,
                                           STATUS_VOID):
            continue

        if frage["source"] == "polymarket":
            status, ausgang, zeitpunkt = pruefe_polymarket(frage)
            geprueft += 1
            time.sleep(PAUSE)
        else:
            # Metaculus (und alles Weitere) gibt den Ausgang mit unserer
            # Zugriffsstufe nicht her - siehe Modul-Docstring.
            status, ausgang, zeitpunkt = STATUS_UNAVAILABLE, None, ""

        eintrag = {
            "id": frage["id"],
            "source": frage["source"],
            "question": frage["question"],
            "status": status,
            "outcome": ausgang,
            "resolved_at": zeitpunkt,
            "checked_at": jetzt,
        }
        bekannt[frage["id"]] = eintrag

        if status == STATUS_RESOLVED:
            neu_aufgeloest += 1
            print(f"  AUFGELOEST [{ausgang}] {frage['question'][:64]}")
        elif status == STATUS_VOID:
            print(f"  annulliert, kein Ausgang: {frage['question'][:56]}")

    RESOLVED_DATEI.parent.mkdir(parents=True, exist_ok=True)
    with open(RESOLVED_DATEI, "w", encoding="utf-8") as datei:
        json.dump(sorted(bekannt.values(), key=lambda e: e["id"]),
                  datei, ensure_ascii=False, indent=2)

    zaehler = {}
    for eintrag in bekannt.values():
        zaehler[eintrag["status"]] = zaehler.get(eintrag["status"], 0) + 1

    print(f"\n{geprueft} Frage(n) bei der Quelle abgefragt, "
          f"{neu_aufgeloest} neu aufgeloest.")
    print(f"Stand in {RESOLVED_DATEI}:")
    for status in (STATUS_RESOLVED, STATUS_OPEN, STATUS_VOID, STATUS_UNAVAILABLE):
        if status in zaehler:
            print(f"  {status:12s} {zaehler[status]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
