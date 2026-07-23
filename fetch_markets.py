"""fetch_markets.py

Laedt offene Fragen von der Polymarket Gamma API und speichert 5 davon
als markets.json. Auswahl: bis zu 3 Fragen mit Afrika-Bezug (maximal eine
pro Event) und aufgefuellt auf 5 mit den liquidesten globalen Wirtschafts-
oder Politikfragen ohne Afrika-Bezug.

Die API ist oeffentlich, es wird kein Key benoetigt.
"""

import json
import sys

import requests

# --- Konstanten ------------------------------------------------------------

BASE_URL = "https://gamma-api.polymarket.com"
ENDPOINT = "/markets"
ANZAHL = 5                 # so viele Fragen wollen wir am Ende speichern
AFRIKA_MAX = 3             # hoechstens so viele Afrika-Fragen, Rest sind Fueller
SEITEN = 20                # so viele Seiten a 100 Markets blaettern wir durch (API begrenzt den Offset)
PRO_SEITE = 100            # Maximum, das die API pro Request zurueckgibt

# Manche Requests wurden ohne User-Agent mit 403 abgewiesen, darum setzen wir einen.
HEADERS = {"User-Agent": "forecasting-mini/1.0"}

# Keywords, um Afrika-Bezug im Fragetext zu erkennen (alles klein geschrieben).
# Bewusst KEINE generischen Woerter "africa"/"african": die matchen auch auf
# "North Africa" und lieferten einen Fehltreffer (eine US-Iran-Frage). Wir
# verlangen darum ein konkretes Land, einen Leadernamen oder eine eindeutige
# Phrase wie "south africa"/"central african".
AFRIKA_KEYWORDS = [
    "nigeria", "kenya", "ethiopia", "egypt",
    "south africa", "ghana", "sudan", "congo", "somalia", "zimbabwe",
    "uganda", "tanzania", "morocco", "algeria", "angola", "senegal",
    "rwanda", "zambia", "tunisia", "libya", "cameroon", "ivory coast",
    "sahel", "ramaphosa", "tinubu", "ruto", "sisi", "akhannouch",
    "central african",
]

# Keywords fuer den Nicht-Afrika-Fueller: globale Wirtschaft oder Politik.
GLOBAL_KEYWORDS = [
    "election", "president", "fed", "interest rate", "inflation", "gdp",
    "recession", "senate", "congress", "parliament", "war", "ceasefire",
    "sanction", "tariff", "trade deal", "prime minister", "government",
    "trump", "putin", "nato", "china", "russia", "ukraine",
]


# --- Daten laden -----------------------------------------------------------

def lade_alle_offenen_markets():
    """Blaettert durch die API und gibt eine Liste offener Markets zurueck.

    Wir fragen mehrere Seiten ab, weil Afrika-Fragen weit hinten liegen und
    nicht in den ersten 100 Markets nach Volumen auftauchen.
    """
    alle = []
    for seite in range(SEITEN):
        offset = seite * PRO_SEITE
        params = {
            "closed": "false",       # nur noch offene Fragen
            "order": "volume",       # nach Handelsvolumen sortieren
            "ascending": "false",    # die groessten zuerst
            "limit": PRO_SEITE,
            "offset": offset,
        }
        antwort = requests.get(
            BASE_URL + ENDPOINT, params=params, headers=HEADERS, timeout=30
        )
        # Die API begrenzt den Offset: zu hohe Werte liefern 422. Das ist kein
        # echter Fehler, sondern heisst "keine weiteren Seiten" -> aufhoeren.
        if antwort.status_code == 422:
            break
        # Bei allen anderen HTTP-Fehlern brechen wir klar ab statt still weiterzulaufen.
        antwort.raise_for_status()

        seiten_daten = antwort.json()
        if not seiten_daten:
            break  # keine weiteren Markets mehr, wir hoeren auf zu blaettern

        alle.extend(seiten_daten)

    print(f"{len(alle)} offene Markets geladen.")
    return alle


# --- Hilfsfunktionen fuer die Auswahl -------------------------------------

def enthaelt_keyword(market, keywords):
    """Prueft, ob eines der Keywords im (kleingeschriebenen) Fragetext steht."""
    frage = market.get("question", "").lower()
    return any(wort in frage for wort in keywords)


def event_id(market):
    """Gibt die Event-ID eines Markets zurueck, sonst None.

    Mehrere Markets zur selben Wahl (z. B. je Partei eine Ja/Nein-Frage)
    teilen sich dieselbe Event-ID. Darueber erkennen wir Duplikate.
    """
    events = market.get("events") or []
    if events:
        return events[0].get("id")
    return None


def volumen(market):
    """Liest das Handelsvolumen als Zahl, fehlt es, zaehlt es als 0."""
    wert = market.get("volume")
    return float(wert) if wert else 0.0


# --- Auswahl ---------------------------------------------------------------

def waehle_afrika(markets):
    """Waehlt Afrika-Markets aus, maximal einen pro Event, nach Volumen sortiert."""
    afrika = [m for m in markets if enthaelt_keyword(m, AFRIKA_KEYWORDS)]
    afrika.sort(key=volumen, reverse=True)  # groesstes Volumen zuerst

    gewaehlt = []
    schon_gesehene_events = set()
    for m in afrika:
        eid = event_id(m)
        # Nur den ersten (groessten) Markt je Event nehmen.
        if eid is not None and eid in schon_gesehene_events:
            continue
        schon_gesehene_events.add(eid)
        gewaehlt.append(m)

    return gewaehlt


def waehle_global_filler(markets, schon_gewaehlt, anzahl):
    """Waehlt die liquidesten globalen Wirtschafts-/Politikfragen ohne Afrika-Bezug."""
    schon_ids = {m.get("id") for m in schon_gewaehlt}

    kandidaten = [
        m for m in markets
        if enthaelt_keyword(m, GLOBAL_KEYWORDS)   # Thema Wirtschaft/Politik
        and not enthaelt_keyword(m, AFRIKA_KEYWORDS)  # aber kein Afrika-Bezug
        and m.get("id") not in schon_ids          # nicht schon gewaehlt
    ]
    kandidaten.sort(key=volumen, reverse=True)

    # Auch hier maximal einen Markt pro Event, damit wir nicht dreimal
    # dieselbe Wahl (z. B. verschiedene Kandidaten) speichern.
    gewaehlt = []
    schon_gesehene_events = set()
    for m in kandidaten:
        eid = event_id(m)
        if eid is not None and eid in schon_gesehene_events:
            continue
        schon_gesehene_events.add(eid)
        gewaehlt.append(m)
        if len(gewaehlt) == anzahl:
            break

    return gewaehlt


# --- Eintrag bauen ---------------------------------------------------------

def baue_eintrag(market, hat_afrika_bezug):
    """Macht aus einem rohen Market-Objekt einen schlanken Eintrag fuer markets.json.

    outcomes und outcomePrices kommen von der API als JSON-String (z. B.
    '["Yes", "No"]'), darum muessen wir sie mit json.loads erneut parsen.
    Die "Yes"-Quote nehmen wir als aktuelle Marktwahrscheinlichkeit market_p.
    """
    outcomes = json.loads(market["outcomes"])          # z. B. ["Yes", "No"]
    preise = json.loads(market["outcomePrices"])       # z. B. ["0.0045", "0.9955"]

    market_p = None
    if "Yes" in outcomes:
        index_yes = outcomes.index("Yes")
        market_p = float(preise[index_yes])

    return {
        "id": market["id"],
        "question": market["question"],
        "market_p": market_p,
        "africa": hat_afrika_bezug,
    }


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_alle_offenen_markets()

    # Afrika-Fragen waehlen und auf hoechstens AFRIKA_MAX begrenzen.
    afrika = waehle_afrika(markets)[:AFRIKA_MAX]
    print(f"{len(afrika)} Afrika-Fragen gewaehlt (max. eine pro Event).")

    # So viele globale Fueller, wie bis ANZAHL noch fehlen.
    rest = ANZAHL - len(afrika)
    filler = waehle_global_filler(markets, afrika, rest)
    print(f"{len(filler)} globale Fueller-Fragen ergaenzt.")

    # Eintraege bauen: Afrika-Fragen mit africa=True, Fueller mit africa=False.
    eintraege = [baue_eintrag(m, True) for m in afrika]
    eintraege += [baue_eintrag(m, False) for m in filler]

    if len(eintraege) < ANZAHL:
        print(
            f"Warnung: nur {len(eintraege)} statt {ANZAHL} Fragen gefunden.",
            file=sys.stderr,
        )

    # ensure_ascii=False, damit Umlaute/Sonderzeichen lesbar bleiben.
    with open("markets.json", "w", encoding="utf-8") as datei:
        json.dump(eintraege, datei, ensure_ascii=False, indent=2)

    print(f"{len(eintraege)} Fragen in markets.json gespeichert.")
    for e in eintraege:
        markierung = "AFRIKA" if e["africa"] else "GLOBAL"
        print(f"  [{markierung}] p={e['market_p']}  {e['question']}")


if __name__ == "__main__":
    main()
