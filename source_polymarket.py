"""source_polymarket.py

Quelle Polymarket: laedt offene Fragen ueber die oeffentliche Gamma API und
gibt sie im gemeinsamen Format zurueck (siehe lade_fragen).

Die API ist oeffentlich, es wird kein Key benoetigt.

Warum /markets/keyset und nicht /markets
----------------------------------------
/markets deckelt den Offset bei 2000. Frueher umgingen wir das, indem wir
dasselbe Fenster mit sechs Sortierungen abfragten und ueber die id
vereinigten - eine Stichprobe, keine vollstaendige Liste. Die API nennt den
richtigen Weg in ihrer eigenen Fehlermeldung:

    HTTP 422  "offset too large, use /markets/keyset for deeper pagination"

/markets/keyset blaettert ueber einen Cursor und hat keine Grenze. Der
Parameter heisst after_cursor - nachgelesen in der OpenAPI-Beschreibung, die
die API unter /openapi.json selbst ausliefert. Geratene Namen (cursor, after,
page_cursor) werden stillschweigend ignoriert und liefern immer wieder die
erste Seite; das faellt ohne Gegenprobe nicht auf.

Gemessen am 31.07.2026: vollstaendig sind es ueber 40'000 offene Markets
statt der ~11'600, die die alte Stichprobe sah. Afrika-Treffer stiegen damit
von 48 auf 60 - der Engpass ist also nicht die Pagination, sondern das
Angebot. Die Liste ist jetzt aber nachweisbar vollstaendig statt gestichprobt.
"""

import json
import sys
import time
from datetime import datetime, timezone

import requests

# --- Konstanten ------------------------------------------------------------

QUELLE = "polymarket"

BASE_URL = "https://gamma-api.polymarket.com"
ENDPOINT = "/markets/keyset"
PRO_SEITE = 100            # Maximum, das die API pro Request zurueckgibt

# Manche Requests wurden ohne User-Agent mit 403 abgewiesen, darum setzen wir einen.
HEADERS = {"User-Agent": "africa-ai-forecasting/1.0"}
TIMEOUT = 30               # Sekunden pro Anfrage, bevor sie als haengend gilt
VERSUCHE = 3               # so oft probieren wir eine Anfrage bei Timeout erneut

# Reissleine gegen eine Endlosschleife, falls der Cursor einmal nicht mehr
# vorwaerts laeuft. Gemessen werden rund 106 Seiten gebraucht; wird die Grenze
# erreicht, melden wir das laut, statt die Liste still abzuschneiden.
MAX_SEITEN = 300

# Vorfilter auf dem Server, rein zur Beschleunigung. Ohne ihn sind es ueber
# 25'000 Markets und der Abruf bricht nicht mehr sauber ab.
#
# Der Wert MUSS deutlich unter MIN_LIQUIDITAET in fetch_markets.py (1200)
# bleiben. Dort steht die eigentliche Regel, hier nur eine Grobsiebung - sonst
# liefe eine spaetere Senkung der Schwelle stillschweigend ins Leere, weil die
# Fragen die Quelle nie verlassen haetten. Genau deshalb wurde dieser Wert
# mitgesenkt, als die Schwelle von 5000 auf 1200 ging.
VORFILTER_VOLUMEN = 400

# Zweiter Vorfilter: Fragen, deren Aufloesungsdatum vorbei ist, verwirft
# fetch_markets.py ohnehin (loest_noch_auf) - sie sind keine Prognosefragen
# mehr, sondern nachgelesene Ergebnisse.
#
# Ein Unterschied bleibt und ist bewusst in Kauf genommen: Markets GANZ OHNE
# endDate laesst loest_noch_auf durch, dieser Serverfilter nicht. Betroffen
# waren zum Messzeitpunkt 1028 Markets, davon 0 mit Afrika-Bezug.
def heute_iso():
    """Heutiges Datum in UTC als YYYY-MM-DD, wie end_date_min es erwartet."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --- Daten laden -----------------------------------------------------------

def hole_seite(params):
    """Holt eine einzelne Seite und wiederholt bei Timeout bis zu VERSUCHE Mal.

    Ein einzelner haengender Request soll bei ueber hundert Anfragen nicht den
    ganzen Lauf abbrechen. Andere Fehler (kein Timeout) reichen wir sofort
    weiter.
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


def lade_alle_markets():
    """Blaettert alle offenen Markets ueber den Cursor durch.

    Rueckgabe ist (markets, vollstaendig). vollstaendig ist False, wenn die
    Reissleine MAX_SEITEN gegriffen hat - der Aufrufer soll den Unterschied
    zwischen "das ist alles" und "hier wurde abgeschnitten" melden koennen.
    """
    markets = {}
    cursor = None

    for seite in range(MAX_SEITEN):
        params = {
            "closed": "false",                     # nur noch offene Fragen
            "limit": PRO_SEITE,
            "volume_num_min": str(VORFILTER_VOLUMEN),
            "end_date_min": heute_iso(),
        }
        if cursor:
            params["after_cursor"] = cursor

        antwort = hole_seite(params)
        antwort.raise_for_status()

        daten = antwort.json()
        teil = daten.get("markets") or []
        for market in teil:
            markets[market["id"]] = market

        cursor = daten.get("next_cursor")
        # Kein Cursor oder leere Seite heisst: wir sind am Ende der Liste.
        if not teil or not cursor:
            return list(markets.values()), True

    return list(markets.values()), False


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


def hole_kategorie_hinweis(market):
    """Gibt "elections" zurueck, wenn die API die Frage als Wahl ausweist, sonst None.

    Das Event-Feld electionType ist bei Wahlfragen mit Werten wie "Presidential",
    "National Assembly" oder "Parliamentary" belegt und bei allen anderen leer.
    Wo es steht, ist die Kategorie ohne Raten klar - das ist verlaesslicher als
    jedes Keyword im Fragetext. fetch_markets.py nimmt diesen Hinweis vorrangig
    und faellt nur sonst auf Keywords zurueck.

    Es ist bewusst nur ein Hinweis und keine fertige Kategorie: die Zuordnung
    selbst gehoert zentral in fetch_markets.py, damit alle Quellen dieselben
    Regeln bekommen.
    """
    event = (market.get("events") or [{}])[0]
    return "elections" if event.get("electionType") else None


def hole_url(market):
    """Baut die oeffentliche Seite des Markts, sonst leeren Text.

    Verlinkt wird das EVENT, nicht der einzelne Markt: das ist die Seite, auf
    der Polymarket den Kursverlauf und das Orderbuch zeigt. Fehlt der Slug,
    geben wir lieber gar keinen Link aus als einen geratenen, der ins Leere
    fuehrt.
    """
    ev = (market.get("events") or [{}])[0]
    if ev.get("slug"):
        return f"https://polymarket.com/event/{ev['slug']}"
    if market.get("slug"):
        return f"https://polymarket.com/market/{market['slug']}"
    return ""


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
        "category_hint": hole_kategorie_hinweis(market),
        "url": hole_url(market),
        # Geplante Aufloesung als ISO-Text. Fuer Polymarket-Fragen entscheidet
        # das Volumen ueber die Auswahl; das Feld ist fuer Fragen ohne
        # Vergleichszahl gedacht und wird hier nur mitgefuehrt, damit alle
        # Quellen dasselbe Format liefern.
        "resolve_time": market.get("endDate") or "",
    }


# --- Oeffentliche Schnittstelle --------------------------------------------

def lade_fragen():
    """Laedt alle offenen Polymarket-Fragen im gemeinsamen Format.

    Gemeinsames Format je Eintrag: id, source, question, market_p,
    benchmark_type, description, volume, event_id, event_title, category_hint.
    Jede Quelle in diesem Projekt stellt genau diese Funktion bereit, damit
    fetch_markets.py sie gleich behandeln kann.

    Die Liste ist vollstaendig, nicht gestichprobt (siehe Modul-Docstring).
    Zwei Vorfilter laufen serverseitig mit, beide unterhalb der Regeln in
    fetch_markets.py: Mindestvolumen und Aufloesungsdatum.
    """
    markets, vollstaendig = lade_alle_markets()

    if not vollstaendig:
        # Nie stillschweigend abschneiden: eine gekuerzte Liste sieht sonst
        # aus wie ein geschrumpftes Angebot.
        print(f"  {QUELLE}: Reissleine bei {MAX_SEITEN} Seiten gegriffen, die "
              f"Liste ist UNVOLLSTAENDIG. Cursor prueft?", file=sys.stderr)

    fragen = [normalisiere(m) for m in markets]
    print(f"  {QUELLE}: {len(fragen)} offene Fragen geladen "
          f"(Volumen ab {VORFILTER_VOLUMEN}, Aufloesung ab heute).")
    return fragen
