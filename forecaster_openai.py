"""forecaster_openai.py

Prognostiker OpenAI. Erzeugt zu einer Frage eine Schaetzung im gemeinsamen
Format (probability, reasoning, confidence) - dasselbe Format, das auch
forecast.py mit Claude erzeugt, damit die Seite beide nebeneinander zeigen kann.

Bewusst ohne das openai-Paket: direkte HTTP-Aufrufe mit requests, genau wie in
den source_*.py. Das haelt die Abhaengigkeiten bei requests und anthropic,
wie CLAUDE.md es vorgibt.

Mit Token gegen die echte API verifiziert (2026-07-29)
-----------------------------------------------------
- Endpoint POST https://api.openai.com/v1/responses, Auth als Bearer-Token.
- Strukturierte Ausgabe liegt unter text.format, NICHT unter response_format.
  Die API weist den alten Namen mit HTTP 400 ab und nennt den neuen selbst.
- temperature wird von gpt-5.6-luna NICHT unterstuetzt (HTTP 400,
  "Unsupported parameter"). Die Prognosen dieses Modells lassen sich darum
  nicht ueber einen Sampling-Parameter stabilisieren - anders als bei Claude
  Haiku 4.5, wo temperature=0 gesetzt wird. Diese Asymmetrie gehoert in jede
  Auswertung, sonst haelt man Sampling-Rauschen fuer einen Modellunterschied.
- Die Antwort enthaelt in output[] zuerst einen reasoning-Block und erst
  danach die message. Auf output[0] zuzugreifen liefert darum nichts.

Bekannte Einschraenkung: keine Web-Suche
----------------------------------------
Claude bekommt in forecast.py ein serverseitiges Web-Such-Tool, dieses Modell
nicht. Der Vergleich misst also nicht nur "Claude gegen GPT", sondern auch
"mit Recherche gegen ohne". Das ist eine echte Verzerrung zugunsten von Claude
bei allem, was nach dem Trainingsstand passiert ist, und muss auf der Seite
und im README stehen, solange es so ist.
"""

import json
import os
import sys

import requests

# --- Konstanten ------------------------------------------------------------

PROGNOSTIKER = "openai"

# Guenstigstes aktuelles Modell der gpt-5.6-Familie ($1 Input / $6 Output je
# 1M Token). Bewusst dieselbe Preisklasse wie claude-haiku-4-5 ($1/$5): ein
# teures Modell gegen ein billiges zu stellen waere kein Modellvergleich,
# sondern ein Preisvergleich.
MODELL = "gpt-5.6-luna"

BASE_URL = "https://api.openai.com/v1/responses"
ENV_DATEI = ".env"
TOKEN_NAME = "OPENAI_API_KEY"
TIMEOUT = 120        # Sekunden; das Modell denkt vor der Antwort nach
MAX_VERSUCHE = 2     # bei ungueltigem JSON genau ein Neuversuch, wie bei Claude

# Anweisung an das Modell. Inhaltlich identisch zum System-Prompt in
# forecast.py - die beiden Modelle muessen dieselbe Aufgabe bekommen, sonst
# vergleicht man Prompts statt Modelle.
ANWEISUNG = (
    "You are a careful forecaster for yes/no questions on politics and "
    "economics. Estimate the probability that the question resolves YES.\n"
    "Read the resolution criteria EXACTLY: check in particular whether a "
    "formal condition must be met (for example an officially signed "
    "agreement), not merely a declaration of intent.\n"
    "Base your estimate on facts and events, never on betting odds or "
    "prediction markets.\n"
    "reasoning must be at most 3 sentences and in English."
)

# Schema fuer die strukturierte Ausgabe. strict=True laesst die API die Form
# erzwingen, statt dass wir hinterher hoffen muessen.
SCHEMA = {
    "type": "object",
    "properties": {
        "probability": {
            "type": "number",
            "description": "Probability between 0 and 1 that the question resolves YES.",
        },
        "reasoning": {
            "type": "string",
            "description": "At most 3 sentences, in English.",
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
    },
    "required": ["probability", "reasoning", "confidence"],
    "additionalProperties": False,
}

# Fehler, bei denen jeder weitere Aufruf genauso scheitern wuerde. Analog zu
# FATALE_FEHLER in forecast.py, hier ueber HTTP-Codes statt Exception-Klassen.
FATALE_CODES = (400, 401, 403, 404)


# --- Token laden -----------------------------------------------------------

def lade_token():
    """Liest OPENAI_API_KEY aus der .env-Datei, sonst aus der Umgebung.

    Gleiche Machart wie in forecast.py und source_metaculus.py. Gibt None
    zurueck, wenn kein Token da ist - dann meldet sich der Prognostiker ab und
    die Pipeline laeuft mit dem anderen Modell weiter.
    """
    if os.path.exists(ENV_DATEI):
        with open(ENV_DATEI, "r", encoding="utf-8") as datei:
            for zeile in datei:
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#") or "=" not in zeile:
                    continue
                name, wert = zeile.split("=", 1)
                if name.strip() == TOKEN_NAME:
                    return wert.strip()

    return os.environ.get(TOKEN_NAME)


# --- Anfrage bauen ---------------------------------------------------------

def baue_eingabe(frage, kriterien):
    """Baut den Eingabetext aus Frage und Aufloesungskriterien.

    Die Marktquote wird NICHT uebergeben - dieselbe methodische Leitplanke wie
    bei Claude. Sonst wuerde das Modell die Marktmeinung nachplappern und der
    Vergleich verloere seinen Sinn.
    """
    kriterien = (kriterien or "").strip()
    if not kriterien:
        return f"Question: {frage}"
    return f"Question: {frage}\n\nResolution criteria:\n{kriterien}"


def baue_body(frage, kriterien):
    """Baut den JSON-Body der Anfrage.

    Kein temperature-Feld: gpt-5.6-luna weist es mit HTTP 400 ab (verifiziert).
    """
    return {
        "model": MODELL,
        "instructions": ANWEISUNG,
        "input": baue_eingabe(frage, kriterien),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "forecast",
                "schema": SCHEMA,
                "strict": True,
            }
        },
    }


# --- Antwort auslesen ------------------------------------------------------

def lies_text(antwort):
    """Holt den Antworttext aus der Responses-API-Struktur.

    Die Liste output[] enthaelt zuerst einen reasoning-Block und erst danach
    die eigentliche message. Wir suchen darum gezielt nach dem Block vom Typ
    output_text, statt auf einen festen Index zuzugreifen.
    """
    for eintrag in antwort.get("output", []) or []:
        for block in eintrag.get("content", []) or []:
            if block.get("type") == "output_text":
                return block.get("text", "")
    return ""


def ist_gueltig(daten):
    """Prueft, ob das JSON das erwartete Schema erfuellt.

    Trotz strict=True pruefen wir selbst nach: die Wertebereiche (0 bis 1)
    garantiert das Schema nicht, und ein Modellwechsel darf hier nicht still
    Unsinn durchlassen.
    """
    if not isinstance(daten, dict):
        return False

    p = daten.get("probability")
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        return False
    if not 0 <= p <= 1:
        return False

    if not isinstance(daten.get("reasoning"), str):
        return False

    return daten.get("confidence") in ("low", "medium", "high")


# --- Oeffentliche Schnittstelle --------------------------------------------

def hole_forecast(token, frage, kriterien):
    """Holt eine Prognose als Dict, oder None.

    Gibt zusaetzlich zurueck, ob der Fehler fatal war, damit der Aufrufer eine
    leere Guthaben- oder Schluesselsituation vom einmaligen Aussetzer
    unterscheiden kann. Rueckgabe: (daten_oder_None, fatal_bool).
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = baue_body(frage, kriterien)

    for versuch in range(MAX_VERSUCHE):
        try:
            antwort = requests.post(BASE_URL, headers=headers, json=body, timeout=TIMEOUT)
        except requests.exceptions.RequestException as fehler:
            print(f"  {PROGNOSTIKER}: Verbindungsfehler ({type(fehler).__name__}).",
                  file=sys.stderr)
            return None, False

        if antwort.status_code in FATALE_CODES:
            meldung = ""
            try:
                meldung = antwort.json().get("error", {}).get("message", "")
            except ValueError:
                meldung = antwort.text[:200]
            print(f"  {PROGNOSTIKER}: Abbruch, HTTP {antwort.status_code}: {meldung}",
                  file=sys.stderr)
            return None, True

        if antwort.status_code != 200:
            # Rate Limit oder Serverfehler: voruebergehend, naechster Versuch.
            print(f"  {PROGNOSTIKER}: HTTP {antwort.status_code}, neuer Versuch ...",
                  file=sys.stderr)
            continue

        daten = None
        try:
            daten = json.loads(lies_text(antwort.json()))
        except (ValueError, TypeError):
            pass

        if daten is not None and ist_gueltig(daten):
            return daten, False

        if versuch == 0:
            print(f"  {PROGNOSTIKER}: ungueltiges JSON, ich frage einmal erneut ...",
                  file=sys.stderr)

    return None, False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    schluessel = lade_token()
    if not schluessel:
        print(f"Fehler: {TOKEN_NAME} ist nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    daten, _ = hole_forecast(
        schluessel,
        "Will Somaliland join the Abraham Accords before 2027?",
        "Resolves Yes only if a formal normalization agreement is signed.",
    )
    print(json.dumps(daten, ensure_ascii=False, indent=2) if daten else "keine Prognose")
