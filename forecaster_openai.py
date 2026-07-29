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

Web-Suche, verifiziert am 2026-07-29
-----------------------------------
Das Modell bekommt dasselbe Zugestaendnis wie Claude: ein serverseitiges
Such-Tool mit gesperrten Wettmarkt-Domains. Ohne das mass der Vergleich nicht
"Claude gegen GPT", sondern "mit Recherche gegen ohne" - bei der Marokko-Frage
sprang dieses Modell von 0.40 ohne Suche auf 0.94 mit Suche, bei einer
Marktquote von 0.90. Die Verzerrung war also groesser als jeder gemessene
Modellunterschied.

- Tool-Typ "web_search", Sperrliste unter filters.blocked_domains.
- Suche und erzwungenes JSON-Schema funktionieren zusammen (beides HTTP 200,
  drei Suchen und trotzdem schemakonformes JSON).
- Suchen erscheinen in output[] als Eintraege vom Typ "web_search_call" und
  lassen sich darueber zaehlen.

Noch offen: ein hartes Limit fuer die Zahl der Suchen wie Claudes max_uses
liess sich nicht verifizieren. Wir zaehlen sie darum nur mit, statt sie zu
deckeln - beobachtet wurden 2 bis 3 pro Frage.
"""

import json
import os
import sys

import requests

import pruefung

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
    "DIRECTION - read carefully: probability is the probability that the "
    "question resolves YES, not the complement. If you conclude the event is "
    "unlikely, the number must be SMALL. Before answering, check that the "
    "number and your reasoning point the same way: reasoning that says "
    "\"unlikely\" must not carry a probability near 1.\n"
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

# Serverseitiges Such-Tool. Dieselben Wettmarkt-Domains sind gesperrt wie bei
# Claude in forecast.py - andernfalls koennte das Modell die Marktquote
# einfach nachlesen, und die methodische Leitplanke des Projekts ("die Quote
# gelangt nie in den Prompt") waere ueber den Umweg der Suche ausgehebelt.
WEB_SEARCH_TOOL = {
    "type": "web_search",
    "filters": {
        "blocked_domains": [
            "polymarket.com",
            "kalshi.com",
            "manifold.markets",
            "predictit.org",
            "metaculus.com",
        ]
    },
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
        "tools": [WEB_SEARCH_TOOL],
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


def zaehle_suchen(antwort):
    """Zaehlt die tatsaechlich ausgefuehrten Web-Suchen.

    Suchen erscheinen in output[] als eigene Eintraege vom Typ
    "web_search_call", neben den reasoning- und message-Eintraegen. Die Zahl
    macht auf der Karte transparent, ob eine Prognose auf Recherche beruht -
    genauso wie num_searches bei Claude.
    """
    return sum(1 for eintrag in antwort.get("output", []) or []
               if eintrag.get("type") == "web_search_call")


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

    Rueckgabe: (daten_oder_None, num_searches, fatal_bool). Das fatal-Flag
    trennt eine leere Guthaben- oder Schluesselsituation vom einmaligen
    Aussetzer - bei ersterer soll der Aufrufer diesen Prognostiker fuer den
    Rest des Laufs abschalten, statt in jeden weiteren Fehler zu laufen.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = baue_body(frage, kriterien)

    letzte_daten = None
    letzter_widerspruch = None
    letzte_suchen = 0

    for versuch in range(MAX_VERSUCHE):
        try:
            antwort = requests.post(BASE_URL, headers=headers, json=body, timeout=TIMEOUT)
        except requests.exceptions.RequestException as fehler:
            print(f"  {PROGNOSTIKER}: Verbindungsfehler ({type(fehler).__name__}).",
                  file=sys.stderr)
            return None, 0, False

        if antwort.status_code in FATALE_CODES:
            meldung = ""
            try:
                meldung = antwort.json().get("error", {}).get("message", "")
            except ValueError:
                meldung = antwort.text[:200]
            print(f"  {PROGNOSTIKER}: Abbruch, HTTP {antwort.status_code}: {meldung}",
                  file=sys.stderr)
            return None, 0, True

        if antwort.status_code != 200:
            # Rate Limit oder Serverfehler: voruebergehend, naechster Versuch.
            print(f"  {PROGNOSTIKER}: HTTP {antwort.status_code}, neuer Versuch ...",
                  file=sys.stderr)
            continue

        roh = antwort.json()
        num_searches = zaehle_suchen(roh)

        daten = None
        try:
            daten = json.loads(lies_text(roh))
        except (ValueError, TypeError):
            pass

        if daten is None or not ist_gueltig(daten):
            if versuch == 0:
                print(f"  {PROGNOSTIKER}: ungueltiges JSON, ich frage einmal "
                      f"erneut ...", file=sys.stderr)
            continue

        # Zahl gegen Begruendung pruefen. Genau dieses Modell hat bei der
        # ICJ-Frage "extraordinarily unlikely" begruendet und 0.995 geliefert.
        widerspruch = pruefung.finde_widerspruch(
            daten["probability"], daten.get("reasoning", ""), frage
        )
        if widerspruch is None:
            return daten, num_searches, False

        letzte_daten, letzter_widerspruch = daten, widerspruch
        letzte_suchen = num_searches
        if versuch == 0:
            print(f"  {PROGNOSTIKER}: unplausibel - "
                  f"{pruefung.beschreibe(daten['probability'], widerspruch)}. "
                  f"Ich frage einmal erneut ...", file=sys.stderr)

    if letzte_daten is not None:
        # Nicht selbst umdrehen: aus "klingt gegenteilig" folgt nicht, dass
        # 1 minus p richtig waere. Behalten und markieren.
        print(f"  {PROGNOSTIKER}: Widerspruch bleibt bestehen, Prognose wird "
              f"markiert.", file=sys.stderr)
        letzte_daten["flagged"] = letzter_widerspruch
        return letzte_daten, letzte_suchen, False

    return None, 0, False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    schluessel = lade_token()
    if not schluessel:
        print(f"Fehler: {TOKEN_NAME} ist nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    daten, suchen, _ = hole_forecast(
        schluessel,
        "Will Somaliland join the Abraham Accords before 2027?",
        "Resolves Yes only if a formal normalization agreement is signed.",
    )
    print(f"{suchen} Web-Suchen")
    print(json.dumps(daten, ensure_ascii=False, indent=2) if daten else "keine Prognose")
