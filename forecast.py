"""forecast.py

Liest die Fragen aus markets.json und erzeugt pro Frage mit der Claude-API
eine strukturierte Prognose als JSON (probability, reasoning, confidence).
Ergebnis wird in forecasts.json gespeichert.

WICHTIG: Die Marktquote (market_p) wird bewusst NICHT an das Modell
uebergeben, damit es den Markt nicht einfach nachplappert.

Der API-Key kommt aus der .env-Datei (oder der Umgebungsvariable
ANTHROPIC_API_KEY) und steht nie im Code.
"""

import json
import os
import sys

import anthropic

# --- Konstanten ------------------------------------------------------------

MODEL = "claude-sonnet-4-6"     # wie in CLAUDE.md vorgegeben
MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
ENV_DATEI = ".env"
MAX_TOKENS = 1024               # die Antwort ist kurz, das reicht locker
PLATZHALTER = "dein-key-hier"   # Platzhalter aus der .env-Vorlage

# System-Prompt: fixiert Rolle und erzwingt reines JSON mit festem Schema.
SYSTEM_PROMPT = (
    "Du bist ein sorgfaeltiger Prognostiker fuer Ja/Nein-Fragen zu Politik "
    "und Wirtschaft. Schaetze die Wahrscheinlichkeit, dass die Frage mit Ja "
    "aufgeloest wird.\n"
    "Antworte AUSSCHLIESSLICH mit einem einzigen JSON-Objekt, ohne Text davor "
    "oder danach und ohne Markdown-Codeblock. Das JSON hat genau diese "
    "Schluessel:\n"
    '  "probability": Zahl zwischen 0 und 1,\n'
    '  "reasoning": kurze Begruendung, maximal 3 Saetze,\n'
    '  "confidence": genau einer der Werte "low", "medium" oder "high".'
)


# --- API-Key laden ---------------------------------------------------------

def lade_env_key():
    """Liest ANTHROPIC_API_KEY aus der .env-Datei, sonst aus der Umgebung.

    Eigener Mini-Reader (keine zusaetzliche Bibliothek): Zeile fuer Zeile
    lesen, Kommentare/Leerzeilen ueberspringen, an erstem '=' aufteilen.
    Findet sich der Key nicht in der .env, versuchen wir die echte
    Umgebungsvariable.
    """
    if os.path.exists(ENV_DATEI):
        with open(ENV_DATEI, "r", encoding="utf-8") as datei:
            for zeile in datei:
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#"):
                    continue  # Leerzeile oder Kommentar
                if "=" not in zeile:
                    continue
                name, wert = zeile.split("=", 1)
                if name.strip() == "ANTHROPIC_API_KEY":
                    return wert.strip()

    # Fallback: echte Umgebungsvariable (gibt None, wenn nicht gesetzt).
    return os.environ.get("ANTHROPIC_API_KEY")


# --- Daten laden -----------------------------------------------------------

def lade_markets():
    """Liest markets.json und gibt die Liste der Fragen zurueck."""
    with open(MARKETS_DATEI, "r", encoding="utf-8") as datei:
        return json.load(datei)


# --- Modell fragen ---------------------------------------------------------

def frage_modell(client, frage):
    """Schickt genau eine Frage an das Modell und gibt den Antworttext zurueck.

    Nur die Frage wird uebergeben, NICHT die Marktquote.
    """
    antwort = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": frage}],
    )

    # Die Antwort besteht aus Bloecken; wir nehmen den ersten Text-Block.
    for block in antwort.content:
        if block.type == "text":
            return block.text
    return ""  # kein Text-Block gefunden (sollte nicht vorkommen)


# --- Antwort pruefen -------------------------------------------------------

def parse_json(text):
    """Versucht, aus dem Antworttext ein JSON-Objekt zu lesen.

    Falls das Modell doch etwas drumherum schreibt, schneiden wir vom ersten
    '{' bis zum letzten '}' aus. Bei ungueltigem JSON geben wir None zurueck.
    """
    start = text.find("{")
    ende = text.rfind("}")
    if start == -1 or ende == -1:
        return None
    try:
        return json.loads(text[start:ende + 1])
    except json.JSONDecodeError:
        return None


def ist_gueltig(daten):
    """Prueft, ob das JSON das erwartete Schema erfuellt."""
    if not isinstance(daten, dict):
        return False

    p = daten.get("probability")
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        return False
    if not (0 <= p <= 1):
        return False

    if not isinstance(daten.get("reasoning"), str):
        return False

    if daten.get("confidence") not in ("low", "medium", "high"):
        return False

    return True


def hole_forecast(client, frage):
    """Holt eine gueltige Prognose; bei ungueltigem JSON genau ein Neuversuch.

    Gibt das gepruefte JSON-Objekt zurueck oder None, falls es zweimal
    scheitert.
    """
    for versuch in range(2):  # 0 = erster Versuch, 1 = ein Neuversuch
        text = frage_modell(client, frage)
        daten = parse_json(text)
        if daten is not None and ist_gueltig(daten):
            return daten
        if versuch == 0:
            print("  Ungueltiges JSON, ich frage genau einmal erneut ...",
                  file=sys.stderr)
    return None


# --- Hauptablauf -----------------------------------------------------------

def main():
    key = lade_env_key()
    if not key or key == PLATZHALTER:
        print(
            "Fehler: Kein API-Key gefunden. Trage deinen Key in die .env-Datei "
            "ein (ANTHROPIC_API_KEY=...) oder setze die Umgebungsvariable.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=key)
    markets = lade_markets()
    print(f"{len(markets)} Fragen aus {MARKETS_DATEI} geladen.")

    forecasts = []
    for i, markt in enumerate(markets, start=1):
        frage = markt["question"]
        print(f"[{i}/{len(markets)}] Frage an das Modell: {frage}")

        daten = hole_forecast(client, frage)
        if daten is None:
            print("  Warnung: keine gueltige Prognose erhalten, ueberspringe.",
                  file=sys.stderr)
            continue

        # Wir speichern die id mit, damit evaluate.py spaeter die Marktquote
        # ueber die id wieder zuordnen kann. Die Quote selbst bleibt hier weg.
        forecasts.append({
            "id": markt["id"],
            "question": frage,
            "probability": daten["probability"],
            "reasoning": daten["reasoning"],
            "confidence": daten["confidence"],
        })
        print(f"  p={daten['probability']}  confidence={daten['confidence']}")

    with open(FORECASTS_DATEI, "w", encoding="utf-8") as datei:
        json.dump(forecasts, datei, ensure_ascii=False, indent=2)

    print(f"{len(forecasts)} Prognosen in {FORECASTS_DATEI} gespeichert.")


if __name__ == "__main__":
    main()
