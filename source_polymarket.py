"""source_polymarket.py

Quelle Polymarket: laedt offene Fragen ueber die oeffentliche Gamma API und
gibt sie im gemeinsamen Format zurueck (siehe lade_fragen).

Die API ist oeffentlich, es wird kein Key benoetigt.
"""

import json
import sys
import time

import requests

# --- Konstanten ------------------------------------------------------------

QUELLE = "polymarket"

BASE_URL = "https://gamma-api.polymarket.com"
ENDPOINT = "/markets"
SEITEN = 21                # Seiten a 100 pro Sortierung (API deckelt den Offset bei 2000)
PRO_SEITE = 100            # Maximum, das die API pro Request zurueckgibt

# Manche Requests wurden ohne User-Agent mit 403 abgewiesen, darum setzen wir einen.
HEADERS = {"User-Agent": "africa-ai-forecasting/1.0"}
TIMEOUT = 30               # Sekunden pro Anfrage, bevor sie als haengend gilt
VERSUCHE = 3               # so oft probieren wir eine Anfrage bei Timeout erneut

# Die API deckelt den Offset bei 2000, eine einzelne Abfrage erreicht also nur
# ~2000 Markets. Weil es aber weit mehr offene Markets gibt und die serverseitige
# Volumen-Sortierung ueber die Seiten hinweg unzuverlaessig ist, laden wir das
# gleiche Fenster mit mehreren Sortierungen und vereinigen die Ergebnisse ueber
# die id. So erwischen wir auch liquide Afrika-Markets, die eine einzelne
# Sortierung verpasst.
SORTIERUNGEN = [
    {},                                             # unsortiert (Standard)
    {"order": "volume", "ascending": "false"},      # groesstes Volumen zuerst
    {"order": "volume", "ascending": "true"},       # kleinstes Volumen zuerst
    {"order": "liquidity", "ascending": "false"},   # nach Liquiditaet
    {"order": "startDate", "ascending": "false"},   # neueste zuerst
    {"order": "endDate", "ascending": "true"},      # bald endende zuerst
]


# --- Daten laden -----------------------------------------------------------

def hole_seite(params):
    """Holt eine einzelne Seite und wiederholt bei Timeout bis zu VERSUCHE Mal.

    Ein einzelner haengender Request soll bei ~126 Anfragen nicht den ganzen
    Lauf abbrechen. Andere Fehler (kein Timeout) reichen wir sofort weiter.
    """
    for versuch in range(1, VERSUCHE + 1):
        try:
            return requests.get(
                BASE_URL + ENDPOINT, params=params, headers=HEADERS, timeout=TIMEOUT
            )
        except requests.exceptions.Timeout:
            if versuch == VERSUCHE:
                raise  # nach dem letzten Versuch klar scheitern lassen
            print(
                f"  Timeout, neuer Versuch {versuch + 1}/{VERSUCHE} ...",
                file=sys.stderr,
            )
            time.sleep(2)  # kurz warten, dann erneut probieren


def lade_seiten(sortierung):
    """Blaettert eine einzelne Sortierung durch und gibt ihre Markets zurueck."""
    markets = []
    for seite in range(SEITEN):
        offset = seite * PRO_SEITE
        params = {
            "closed": "false",   # nur noch offene Fragen
            "limit": PRO_SEITE,
            "offset": offset,
        }
        params.update(sortierung)  # z. B. order=volume, ascending=false

        antwort = hole_seite(params)
        # Die API begrenzt den Offset: zu hohe Werte liefern 422. Das ist kein
        # echter Fehler, sondern heisst "keine weiteren Seiten" -> aufhoeren.
        if antwort.status_code == 422:
            break
        # Bei allen anderen HTTP-Fehlern brechen wir klar ab statt still weiterzulaufen.
        antwort.raise_for_status()

        seiten_daten = antwort.json()
        if not seiten_daten:
            break  # keine weiteren Markets mehr, wir hoeren auf zu blaettern

        markets.extend(seiten_daten)

    return markets


# --- Felder auslesen -------------------------------------------------------

def hole_market_p(market):
    """Gibt die "Yes"-Quote eines Markets als Zahl zurueck, sonst None.

    outcomes und outcomePrices kommen von der API als JSON-String (z. B.
    '["Yes", "No"]' bzw. '["0.0045", "0.9955"]'), darum parsen wir sie mit
    json.loads. Fehlt ein "Yes"-Outcome oder ist der Text ungueltig, gibt es
    keine Quote (None).

    Achtung: es gibt Markets, die ein "Yes"-Outcome fuehren, aber eine kuerzere
    oder leere Preisliste liefern. Wir pruefen die Laenge darum explizit, statt
    blind zu indizieren - sonst reisst ein einzelner solcher Markt den ganzen
    Lauf ab, und wir fragen hier ueber 2000 Markets ab.
    """
    try:
        outcomes = json.loads(market.get("outcomes", "[]"))
        preise = json.loads(market.get("outcomePrices", "[]"))
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(outcomes, list) or not isinstance(preise, list):
        return None

    if "Yes" not in outcomes:
        return None

    index_yes = outcomes.index("Yes")
    if index_yes >= len(preise):
        return None  # Outcome vorhanden, aber kein zugehoeriger Preis

    try:
        return float(preise[index_yes])
    except (TypeError, ValueError):
        return None  # Preis ist kein gueltiger Zahlentext


def hole_volumen(market):
    """Liest das Handelsvolumen als Zahl, fehlt es, zaehlt es als 0."""
    wert = market.get("volume")
    return float(wert) if wert else 0.0


def hole_event(market):
    """Gibt (event_id, event_titel) des Markets zurueck.

    Polymarket buendelt zusammengehoerende Fragen in einem Event: die zwoelf
    Kandidatenfragen zur Wahl in Guinea-Bissau haengen alle am selben Event.
    Ueber diese id erkennt fetch_markets.py Varianten derselben Sache und nimmt
    nur eine davon.

    Das Feld heisst "events" und ist eine Liste; in der Praxis steht dort genau
    ein Event. Wir nehmen den ersten Eintrag. Fehlt die Liste oder hat der
    Eintrag keine id, faellt der Schluessel auf die Market-id zurueck - so eine
    Frage bildet dann ihr eigenes Event und wird nie faelschlich mit einer
    anderen zusammengeworfen.
    """
    events = market.get("events") or []
    if events and events[0].get("id"):
        return events[0]["id"], events[0].get("title", "")

    return f"einzel-{market['id']}", market.get("question", "")


def normalisiere(market):
    """Macht aus einem rohen Polymarket-Objekt einen Eintrag im gemeinsamen Format.

    Die id wird mit dem Quellennamen kombiniert, damit sie auch dann eindeutig
    bleibt, wenn eine andere Quelle zufaellig dieselbe Nummer vergibt. Fuer die
    event_id gilt dasselbe.
    """
    event_id, event_titel = hole_event(market)

    return {
        "id": f"{QUELLE}-{market['id']}",
        "source": QUELLE,
        "question": market["question"],
        "market_p": hole_market_p(market),
        "benchmark_type": "market_price",  # echter Geldmarkt, kein Community-Median
        "description": market.get("description", ""),
        "volume": hole_volumen(market),
        "event_id": f"{QUELLE}-{event_id}",
        "event_title": event_titel,
    }


# --- Oeffentliche Schnittstelle --------------------------------------------

def lade_fragen():
    """Laedt alle offenen Polymarket-Fragen im gemeinsamen Format.

    Gemeinsames Format je Eintrag: id, source, question, market_p,
    benchmark_type, description, volume, event_id, event_title. Jede Quelle in
    diesem Projekt stellt genau diese Funktion bereit, damit fetch_markets.py
    sie gleich behandeln kann.

    Eine einzelne Abfrage erreicht wegen des Offset-Deckels nur ~2000 Markets,
    und die serverseitige Volumen-Sortierung ist ueber die Seiten hinweg
    unzuverlaessig. Darum kombinieren wir mehrere Sortierungen und vereinigen
    ueber die id.
    """
    nach_id = {}  # id -> market, dadurch werden Duplikate automatisch entfernt
    for sortierung in SORTIERUNGEN:
        for market in lade_seiten(sortierung):
            nach_id[market["id"]] = market

    fragen = [normalisiere(m) for m in nach_id.values()]
    print(f"  {QUELLE}: {len(fragen)} eindeutige offene Fragen geladen "
          f"(aus {len(SORTIERUNGEN)} Sortierungen).")
    return fragen
