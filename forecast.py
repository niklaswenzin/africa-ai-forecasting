"""forecast.py

Liest die Fragen aus markets.json und erzeugt pro Frage mit der Claude-API
eine strukturierte Prognose als JSON (probability, reasoning, confidence).
Das Modell darf pro Frage selbst entscheiden, ob es vorher die Web-Suche
nutzt (serverseitiges Tool). Ergebnis wird in forecasts.json gespeichert.

WICHTIG: Die Marktquote (market_p) wird bewusst NICHT an das Modell
uebergeben, damit es den Markt nicht einfach nachplappert.

Der API-Key kommt aus der .env-Datei (oder der Umgebungsvariable
ANTHROPIC_API_KEY) und steht nie im Code.
"""

import json
import os
import sys

import anthropic

import forecaster_openai

# --- Konstanten ------------------------------------------------------------

# Guenstigstes aktuelles Claude-Modell ($1 Input / $5 Output je 1M Token,
# vorher claude-sonnet-4-6 mit $3/$15). Bewusst dieselbe Preisklasse wie
# gpt-5.6-luna in forecaster_openai.py: sonst vergleicht man Preise statt
# Modelle.
#
# Einschraenkung, die wir bewusst in Kauf nehmen: Haiku liest die
# Aufloesungskriterien weniger genau als Sonnet. Genau daran haengt dieses
# Projekt aber (Absichtserklaerung gegen formales Abkommen), also ist mit
# schwaecheren Prognosen zu rechnen.
MODEL = "claude-haiku-4-5"
PROGNOSTIKER = "claude"         # Schluessel im forecasts.json-Eintrag

# Haiku 4.5 akzeptiert Sampling-Parameter, neuere Modelle nicht mehr. 0 macht
# die Prognosen ueber Laeufe hinweg stabiler - das ist noetig, weil dieselbe
# Frage sonst zwischen Laeufen um bis zu 44 Punkte springt. Achtung: das
# OpenAI-Modell unterstuetzt temperature NICHT, dort geht das nicht.
TEMPERATURE = 0

MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
ENV_DATEI = ".env"
MAX_TOKENS = 4096               # mehr Platz, weil Suchergebnisse dazukommen
PLATZHALTER = "dein-key-hier"   # Platzhalter aus der .env-Vorlage
MAX_PAUSE_RUNDEN = 5            # Sicherheitsgrenze fuer die pause_turn-Schleife
SUCH_BUDGET = 3                 # hartes Limit: so viele Suchen INSGESAMT pro Frage

# Fehler, bei denen jeder weitere Aufruf genauso scheitern wuerde: leeres
# Guthaben (BadRequest), ungueltiger Key, gesperrter Zugang. Bei diesen brechen
# wir die Schleife ab, statt fuer jede weitere Frage in denselben Fehler zu
# laufen. Alle uebrigen API-Fehler gelten als voruebergehend.
FATALE_FEHLER = (
    anthropic.BadRequestError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
)

# Serverseitiges Web-Such-Tool. Claude entscheidet pro Frage selbst, ob es
# sucht. Wettquoten-/Prediction-Market-Seiten sind gesperrt, damit das Modell
# nicht einfach die Marktmeinung nachplappert.
# Hinweis: max_uses gilt PRO Request. Weil die serverseitige Suche pausieren und
# neu starten kann, setzen wir max_uses spaeter pro Runde auf das Restbudget,
# damit die Gesamtzahl der Suchen pro Frage SUCH_BUDGET nicht ueberschreitet.
# Achtung Tool-Version: web_search_20260209 (mit dynamischer Filterung) laeuft
# nur auf den neueren Modellen. Haiku 4.5 braucht die Basisvariante
# web_search_20250305 - ein reiner Modellwechsel ohne diese Zeile haette die
# Pipeline zerlegt.
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "blocked_domains": [
        "polymarket.com",
        "kalshi.com",
        "manifold.markets",
        "predictit.org",
    ],
}

# System-Prompt: fixiert Rolle und erzwingt reines JSON mit festem Schema.
SYSTEM_PROMPT = (
    "Du bist ein sorgfaeltiger Prognostiker fuer Ja/Nein-Fragen zu Politik "
    "und Wirtschaft. Schaetze die Wahrscheinlichkeit, dass die Frage mit Ja "
    "aufgeloest wird.\n"
    "Beachte die Aufloesungskriterien GENAU: pruefe insbesondere, ob eine "
    "formale Bedingung erfuellt sein muss (z. B. ein offiziell unterzeichnetes "
    "Abkommen), und nicht nur eine Absichtserklaerung.\n"
    "Du DARFST die Web-Suche nutzen, wenn aktuelle Fakten die Antwort "
    "veraendern wuerden. Stuetze dich dabei auf Ereignisse und Nachrichten, "
    "NICHT auf Wettquoten oder Prediction-Markets.\n"
    "Deine LETZTE Nachricht muss ein einziges JSON-Objekt sein, ohne Text "
    "davor oder danach und ohne Markdown-Codeblock. Das JSON hat genau diese "
    "Schluessel:\n"
    '  "probability": Zahl zwischen 0 und 1,\n'
    '  "reasoning": kurze Begruendung, maximal 3 Saetze, auf ENGLISCH,\n'
    '  "confidence": genau einer der Werte "low", "medium" oder "high".\n'
    "Das Feld reasoning muss auf Englisch sein, weil es unveraendert auf der "
    "oeffentlichen Dashboard-Seite erscheint. Die uebrigen Felder sind Zahlen "
    "bzw. feste Schluesselwoerter und bleiben unveraendert."
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


def lade_alte_forecasts():
    """Liest die bisherige forecasts.json als Dict id -> Eintrag.

    Dient als Rueckfallebene: schlaegt eine Frage im aktuellen Lauf fehl,
    uebernehmen wir ihre letzte Prognose, damit die Seite vollstaendig bleibt.
    Existiert die Datei noch nicht oder ist sie beschaedigt, starten wir
    einfach ohne Rueckfallebene - das ist kein Grund abzubrechen.
    """
    try:
        with open(FORECASTS_DATEI, "r", encoding="utf-8") as datei:
            alte = json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    return {eintrag["id"]: umform_alt(eintrag) for eintrag in alte if "id" in eintrag}


def umform_alt(eintrag):
    """Bringt einen Eintrag aus dem alten Ein-Modell-Format ins neue Format.

    Frueher stand die Prognose flach im Eintrag (probability, reasoning,
    confidence), weil es nur Claude gab. Jetzt liegen beide Modelle unter
    "forecasts". Alte Eintraege wandern unter den Claude-Schluessel, statt
    beim Einlesen einen Fehler auszuloesen - sie stammen zwar von einem
    anderen Claude-Modell, sind aber besser als eine leere Karte.
    """
    if "forecasts" in eintrag:
        return eintrag

    if "probability" not in eintrag:
        return {"id": eintrag["id"], "question": eintrag.get("question", ""),
                "forecasts": {}}

    return {
        "id": eintrag["id"],
        "question": eintrag.get("question", ""),
        "forecasts": {
            PROGNOSTIKER: {
                "probability": eintrag["probability"],
                "reasoning": eintrag.get("reasoning", ""),
                "confidence": eintrag.get("confidence", ""),
                "searched": eintrag.get("searched", False),
                "num_searches": eintrag.get("num_searches", 0),
            }
        },
    }


# --- Prompt bauen ----------------------------------------------------------

def baue_user_prompt(markt):
    """Baut die User-Nachricht aus Frage und Aufloesungskriterien.

    Die Kriterien (description) sind die Regeln der Frage, NICHT die Marktquote,
    und duerfen darum in den Prompt. Fehlt die description, geben wir nur die
    Frage.
    """
    frage = markt["question"]
    kriterien = markt.get("description", "").strip()
    if not kriterien:
        return frage
    return f"Frage: {frage}\n\nAufloesungskriterien:\n{kriterien}"


# --- Modell fragen ---------------------------------------------------------

def frage_modell(client, frage):
    """Schickt eine Frage ans Modell, erlaubt Web-Suche, und gibt (text, num_searches) zurueck.

    Nur die Frage wird uebergeben, NICHT die Marktquote. Weil die Web-Suche
    serverseitig laeuft, kann die Antwort mit stop_reason "pause_turn" pausieren;
    dann haengen wir die bisherige Antwort an und senden erneut. Am Ende zaehlt
    das JSON im LETZTEN Text-Block (nach der Suche).
    """
    messages = [{"role": "user", "content": frage}]
    num_searches = 0

    for _ in range(MAX_PAUSE_RUNDEN):
        rest_budget = SUCH_BUDGET - num_searches
        if rest_budget > 0:
            # Tool erlauben, aber max_uses auf das Restbudget dieser Frage begrenzen.
            tool = dict(WEB_SEARCH_TOOL, max_uses=rest_budget)
            antwort = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                tools=[tool],
                messages=messages,
            )
        else:
            # Budget aufgebraucht -> Suche verbieten, Antwort erzwingen.
            antwort = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                tools=[WEB_SEARCH_TOOL],
                tool_choice={"type": "none"},
                messages=messages,
            )

        # Nur echte Web-Suchen zaehlen. Die _20260209-Tool-Version fuehrt intern
        # zusaetzlich code_execution aus (dynamisches Filtern der Treffer) - das
        # sind ebenfalls server_tool_use-Bloecke, aber keine Suchen.
        for block in antwort.content:
            if block.type == "server_tool_use" and getattr(block, "name", None) == "web_search":
                num_searches += 1

        # Serverseitige Tool-Schleife noch nicht fertig -> anhaengen, weiter.
        if antwort.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": antwort.content})
            continue

        # Fertig: den LETZTEN Text-Block nehmen (das JSON steht am Schluss).
        text = ""
        for block in antwort.content:
            if block.type == "text":
                text = block.text
        return text, num_searches

    # Rundenlimit erreicht (sollte selten sein): mit leerem Text zurueck.
    return "", num_searches


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

    Gibt (JSON-Objekt, num_searches) zurueck, oder (None, num_searches), falls
    es zweimal scheitert.
    """
    for versuch in range(2):  # 0 = erster Versuch, 1 = ein Neuversuch
        text, num_searches = frage_modell(client, frage)
        daten = parse_json(text)
        if daten is not None and ist_gueltig(daten):
            return daten, num_searches
        if versuch == 0:
            print("  Ungueltiges JSON, ich frage genau einmal erneut ...",
                  file=sys.stderr)
    return None, num_searches


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

    # Bisherige Prognosen als Rueckfallebene: schlaegt eine Frage jetzt fehl,
    # behalten wir ihren letzten guten Stand, statt sie ersatzlos zu verlieren.
    alte = lade_alte_forecasts()

    # Zweiter Prognostiker. Fehlt sein Token, laeuft der Lauf einfach nur mit
    # Claude weiter - eine halbe Vergleichstabelle ist besser als gar keine.
    openai_token = forecaster_openai.lade_token()
    if not openai_token:
        print(f"Hinweis: kein {forecaster_openai.TOKEN_NAME} gesetzt, "
              f"es wird nur {PROGNOSTIKER} prognostiziert.", file=sys.stderr)

    forecasts = []
    abgebrochen = False
    openai_abgebrochen = False

    for i, markt in enumerate(markets, start=1):
        frage = markt["question"]
        prompt = baue_user_prompt(markt)  # Frage + Aufloesungskriterien
        print(f"[{i}/{len(markets)}] {frage}")

        eintrag_forecasts = {}

        # --- Claude ---
        try:
            daten, num_searches = hole_forecast(client, prompt)
        except FATALE_FEHLER as fehler:
            # Kein Guthaben, ungueltiger Key, gesperrter Zugang: die naechsten
            # Fragen wuerden genauso scheitern. Schleife sofort beenden und
            # das Erreichte sichern, statt sinnlos weiterzulaufen.
            print(f"  Abbruch {PROGNOSTIKER}: {type(fehler).__name__}: {fehler}",
                  file=sys.stderr)
            abgebrochen = True
            break
        except anthropic.APIError as fehler:
            # Voruebergehend (Rate Limit, Serverfehler, Verbindung): nur diese
            # eine Frage ueberspringen, die uebrigen weiter versuchen.
            print(f"  Warnung {PROGNOSTIKER}: {type(fehler).__name__}, uebersprungen.",
                  file=sys.stderr)
            daten, num_searches = None, 0

        if daten is not None:
            eintrag_forecasts[PROGNOSTIKER] = {
                "probability": daten["probability"],
                "reasoning": daten["reasoning"],
                "confidence": daten["confidence"],
                "searched": num_searches > 0,
                "num_searches": num_searches,
            }
            print(f"  {PROGNOSTIKER}: p={daten['probability']} "
                  f"({daten['confidence']}, {num_searches} Suchen)")

        # --- OpenAI ---
        if openai_token and not openai_abgebrochen:
            gpt, gpt_suchen, fatal = forecaster_openai.hole_forecast(
                openai_token, frage, markt.get("description", "")
            )
            if fatal:
                # Gleiche Logik wie oben: kein Guthaben oder ungueltiger Key
                # wiederholt sich bei jeder weiteren Frage. Claude laeuft aber
                # weiter, darum nur diesen Prognostiker abschalten.
                openai_abgebrochen = True
            elif gpt is not None:
                eintrag_forecasts[forecaster_openai.PROGNOSTIKER] = {
                    "probability": gpt["probability"],
                    "reasoning": gpt["reasoning"],
                    "confidence": gpt["confidence"],
                    "searched": gpt_suchen > 0,
                    "num_searches": gpt_suchen,
                }
                print(f"  {forecaster_openai.PROGNOSTIKER}: p={gpt['probability']} "
                      f"({gpt['confidence']}, {gpt_suchen} Suchen)")

        if not eintrag_forecasts:
            print("  Warnung: kein Modell hat eine gueltige Prognose geliefert.",
                  file=sys.stderr)
            continue

        # Wir speichern die id mit, damit evaluate.py spaeter die Marktquote
        # ueber die id wieder zuordnen kann. Die Quote selbst bleibt hier weg.
        # Beide Modelle liegen unter "forecasts", damit ein drittes spaeter
        # ohne Schema-Aenderung dazukommen kann.
        forecasts.append({
            "id": markt["id"],
            "question": frage,
            "forecasts": eintrag_forecasts,
        })

    # Fuer jede Frage ohne frische Prognose die alte uebernehmen, falls es eine
    # gibt. So bleibt die Seite vollstaendig, auch wenn ein Lauf mittendrin
    # scheitert; veraltete Eintraege sind besser als fehlende Karten.
    frisch = {f["id"] for f in forecasts}
    uebernommen = 0
    for markt in markets:
        if markt["id"] not in frisch and markt["id"] in alte:
            forecasts.append(alte[markt["id"]])
            uebernommen += 1

    if uebernommen:
        print(f"{uebernommen} Prognose(n) aus dem letzten Lauf uebernommen.")

    # Nie eine leere Datei schreiben: das wuerde den letzten guten Stand
    # zerstoeren und evaluate.py sowie build_site.py ins Leere laufen lassen.
    if not forecasts:
        print(f"Fehler: keine einzige Prognose vorhanden. {FORECASTS_DATEI} "
              f"wird NICHT ueberschrieben.", file=sys.stderr)
        sys.exit(1)

    with open(FORECASTS_DATEI, "w", encoding="utf-8") as datei:
        json.dump(forecasts, datei, ensure_ascii=False, indent=2)

    print(f"{len(forecasts)} Prognosen in {FORECASTS_DATEI} gespeichert.")

    # Nach einem Abbruch mit Fehlercode enden, damit der Lauf nicht faelschlich
    # als erfolgreich gilt - die Datei ist aber gesichert.
    if abgebrochen:
        sys.exit(1)


if __name__ == "__main__":
    main()
