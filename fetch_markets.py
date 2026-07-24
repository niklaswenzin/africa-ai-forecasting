"""fetch_markets.py

Laedt offene Fragen von der Polymarket Gamma API und speichert 5 davon
als markets.json. Design: 5 Fragen mit Afrika-Bezug, maximal eine pro Land,
keine Sport-Fragen. Bevorzugt werden Fragen mit einer Marktquote zwischen
0.05 und 0.95 (nach Volumen sortiert); Extremwerte nur, falls sonst keine 5
zusammenkommen. Bleiben nach allen Filtern weniger als 5 uebrig, speichern
wir alle vorhandenen und melden die Luecke, statt mit anderen Themen aufzufuellen.

Die API ist oeffentlich, es wird kein Key benoetigt.
"""

import json
import re
import sys
import time

import requests

# --- Konstanten ------------------------------------------------------------

BASE_URL = "https://gamma-api.polymarket.com"
ENDPOINT = "/markets"
ANZAHL = 5                 # so viele Afrika-Fragen wollen wir am Ende speichern
MODERAT_MIN = 0.05         # bevorzugte Quote: nicht extremer als diese Grenzen
MODERAT_MAX = 0.95
SEITEN = 21                # Seiten a 100 pro Sortierung (API deckelt den Offset bei 2000)
PRO_SEITE = 100            # Maximum, das die API pro Request zurueckgibt

# Manche Requests wurden ohne User-Agent mit 403 abgewiesen, darum setzen wir einen.
HEADERS = {"User-Agent": "forecasting-mini/1.0"}
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

# Zuordnung Keyword -> Land, um Afrika-Bezug im Fragetext zu erkennen (alles
# klein geschrieben). Auch Leader-Namen (z. B. "abiy ahmed" -> Aethiopien)
# zeigen auf ihr Land, damit wir spaeter pro Land nur eine Frage nehmen.
# Wir matchen auf Wortgrenzen, damit "niger" NICHT in "Nigeria" und "mali"
# NICHT in "Somalia" faelschlich anschlaegt. Bewusst NICHT drin: das generische
# "africa" (matcht "North Africa") und "chad" (matcht die Personen "Chad
# Bianco"/"Chad Patrick", nicht den Staat).
#
# Reihenfolge wichtig: spezifischere Keywords zuerst, damit "south sudan" vor
# "sudan" greift; land_von_market nimmt das erste passende Keyword.
AFRIKA_LAND = {
    "south sudan": "South Sudan",
    "guinea-bissau": "Guinea-Bissau",
    "central african": "Central African Republic",
    "south africa": "South Africa",
    "burkina faso": "Burkina Faso",
    "sierra leone": "Sierra Leone",
    "ivory coast": "Ivory Coast",
    "somaliland": "Somaliland",
    "nigeria": "Nigeria", "tinubu": "Nigeria",
    "kenya": "Kenya", "ruto": "Kenya",
    "ethiopia": "Ethiopia", "abiy ahmed": "Ethiopia",
    "egypt": "Egypt",
    "ghana": "Ghana",
    "sudan": "Sudan",
    "somalia": "Somalia",
    "zimbabwe": "Zimbabwe",
    "uganda": "Uganda",
    "tanzania": "Tanzania",
    "morocco": "Morocco", "akhannouch": "Morocco",
    "algeria": "Algeria",
    "angola": "Angola",
    "senegal": "Senegal",
    "rwanda": "Rwanda",
    "zambia": "Zambia",
    "tunisia": "Tunisia",
    "libya": "Libya",
    "cameroon": "Cameroon",
    "gabon": "Gabon",
    "mozambique": "Mozambique",
    "malawi": "Malawi",
    "botswana": "Botswana",
    "namibia": "Namibia",
    "mauritania": "Mauritania",
    "liberia": "Liberia",
    "congo": "Congo",
    "mali": "Mali",
    "niger": "Niger",
    "togo": "Togo",
    "benin": "Benin",
    "eritrea": "Eritrea",
    "djibouti": "Djibouti",
    "madagascar": "Madagascar",
    "lesotho": "Lesotho",
    "eswatini": "Eswatini",
    "ramaphosa": "South Africa",
    "sahel": "Sahel",
}

# Aus dem Dict abgeleitete Liste aller Afrika-Keywords (einzige Quelle: AFRIKA_LAND).
AFRIKA_KEYWORDS = list(AFRIKA_LAND.keys())

# Sport-Begriffe: matcht einer davon, verwerfen wir den Markt als Afrika-Frage.
# Grund: Laendernamen tauchen auch in Sport-Fragen auf (z. B. Cricket "T20
# Namibia ... vs Uganda"). Die API liefert leider keine Kategorie/Tags, darum
# diese Negativliste als einfacher, gut lesbarer Ersatz.
SPORT_KEYWORDS = [
    "cricket", "cup", "league", "fifa", "uefa", "nba", "nfl", "mlb",
    "t20", "odi", "tournament", "quadrangular", " vs ", "vs.", " fc ", "match",
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


def lade_alle_offenen_markets():
    """Laedt offene Markets ueber mehrere Sortierungen und vereinigt sie ueber die id.

    Eine einzelne Abfrage erreicht wegen des Offset-Deckels nur ~2000 Markets,
    und die serverseitige Volumen-Sortierung ist ueber die Seiten hinweg
    unzuverlaessig. Darum kombinieren wir mehrere Sortierungen. Am Ende
    sortieren wir clientseitig selbst nach Volumen, statt der API zu vertrauen.
    """
    nach_id = {}  # id -> market, dadurch werden Duplikate automatisch entfernt
    for sortierung in SORTIERUNGEN:
        for market in lade_seiten(sortierung):
            nach_id[market["id"]] = market

    alle = list(nach_id.values())
    alle.sort(key=volumen, reverse=True)  # clientseitig: groesstes Volumen zuerst

    print(f"{len(alle)} eindeutige offene Markets geladen (aus {len(SORTIERUNGEN)} Sortierungen).")
    return alle


# --- Hilfsfunktionen fuer die Auswahl -------------------------------------

def enthaelt_wort(market, keywords):
    """Prueft, ob eines der Keywords als ganzes Wort im Fragetext steht.

    Wortgrenzen (nicht bloss Teilstring), damit "niger" nicht in "Nigeria" und
    "mali" nicht in "Somalia" faelschlich anschlaegt. Mehrwort-Phrasen wie
    "south africa" funktionieren damit ebenfalls.
    """
    frage = market.get("question", "").lower()
    for wort in keywords:
        # (?<![a-z]) und (?![a-z]): links und rechts kein weiterer Buchstabe.
        if re.search(r"(?<![a-z])" + re.escape(wort) + r"(?![a-z])", frage):
            return True
    return False


def enthaelt_teilstring(market, keywords):
    """Prueft, ob eines der Keywords als Teilstring im Fragetext steht.

    Fuer Sport-Begriffe wie " vs " oder "t20", die keine Wortgrenzen brauchen.
    """
    frage = market.get("question", "").lower()
    return any(wort in frage for wort in keywords)


def ist_sport(market):
    """True, wenn die Frage nach Sport aussieht (Cricket, Cup, "vs" usw.)."""
    return enthaelt_teilstring(market, SPORT_KEYWORDS)


def hat_afrika_bezug(market):
    """True, wenn ein Afrika-Keyword vorkommt UND es keine Sport-Frage ist."""
    return enthaelt_wort(market, AFRIKA_KEYWORDS) and not ist_sport(market)


def land_von_market(market):
    """Gibt das Land der Frage zurueck (erstes passendes Keyword aus AFRIKA_LAND).

    Reihenfolge im Dict sorgt dafuer, dass spezifische Keywords zuerst greifen
    (z. B. "south sudan" vor "sudan"). Fehlt ein Treffer, nehmen wir die id als
    eigenes Land, damit so ein Markt nie faelschlich mit einem anderen zusammenfaellt.
    """
    frage = market.get("question", "").lower()
    for wort, land in AFRIKA_LAND.items():
        if re.search(r"(?<![a-z])" + re.escape(wort) + r"(?![a-z])", frage):
            return land
    return market.get("id")


def volumen(market):
    """Liest das Handelsvolumen als Zahl, fehlt es, zaehlt es als 0."""
    wert = market.get("volume")
    return float(wert) if wert else 0.0


def hole_market_p(market):
    """Gibt die "Yes"-Quote eines Markets als Zahl zurueck, sonst None.

    outcomes und outcomePrices kommen von der API als JSON-String (z. B.
    '["Yes", "No"]' bzw. '["0.0045", "0.9955"]'), darum parsen wir sie mit
    json.loads. Fehlt ein "Yes"-Outcome oder ist der Text ungueltig, gibt es
    keine Quote (None).
    """
    try:
        outcomes = json.loads(market.get("outcomes", "[]"))
        preise = json.loads(market.get("outcomePrices", "[]"))
    except (json.JSONDecodeError, TypeError):
        return None

    if "Yes" in outcomes:
        index_yes = outcomes.index("Yes")
        return float(preise[index_yes])
    return None


def ist_moderat(market):
    """True, wenn die Quote existiert und nicht extrem ist (zwischen den Grenzen)."""
    p = hole_market_p(market)
    return p is not None and MODERAT_MIN <= p <= MODERAT_MAX


# --- Auswahl ---------------------------------------------------------------

def _hoechstes_volumen_pro_land(markets, gewaehlt, gesehene_laender):
    """Geht Markets (schon nach Volumen sortiert) durch und nimmt je Land den ersten.

    Arbeitet auf den uebergebenen Listen/Mengen weiter, damit ein erster Durchlauf
    (moderate Quoten) und ein zweiter Durchlauf (Extremwerte) sich nicht in die
    Quere kommen: ein Land, das schon vertreten ist, wird nie doppelt genommen.
    """
    for m in markets:
        if len(gewaehlt) == ANZAHL:
            break
        land = land_von_market(m)
        if land in gesehene_laender:
            continue
        gesehene_laender.add(land)
        gewaehlt.append(m)


def waehle_afrika(markets):
    """Waehlt bis zu ANZAHL Afrika-Fragen: max. eine pro Land, kein Sport.

    Bevorzugt Quoten zwischen MODERAT_MIN und MODERAT_MAX (erster Durchlauf).
    Nur wenn so keine ANZAHL zusammenkommen, sind Extremwerte erlaubt (zweiter
    Durchlauf). Innerhalb jedes Durchlaufs entscheidet das Volumen.
    """
    afrika = [m for m in markets if hat_afrika_bezug(m)]
    afrika.sort(key=volumen, reverse=True)  # groesstes Volumen zuerst

    moderate = [m for m in afrika if ist_moderat(m)]
    extreme = [m for m in afrika if not ist_moderat(m)]

    gewaehlt = []
    gesehene_laender = set()
    _hoechstes_volumen_pro_land(moderate, gewaehlt, gesehene_laender)  # 1. bevorzugt
    _hoechstes_volumen_pro_land(extreme, gewaehlt, gesehene_laender)   # 2. Notnagel
    return gewaehlt


# --- Eintrag bauen ---------------------------------------------------------

def baue_eintrag(market):
    """Macht aus einem rohen Market-Objekt einen schlanken Eintrag fuer markets.json.

    Die Marktquote (market_p) holen wir ueber hole_market_p. Da wir nur noch
    Afrika-Fragen speichern, ist "africa" immer True.
    """
    return {
        "id": market["id"],
        "question": market["question"],
        "market_p": hole_market_p(market),
        "africa": True,
    }


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_alle_offenen_markets()

    afrika = waehle_afrika(markets)
    print(f"{len(afrika)} Afrika-Fragen gewaehlt (max. eine pro Land, kein Sport).")

    eintraege = [baue_eintrag(m) for m in afrika]

    # Weniger als ANZAHL? Dann NICHT mit anderen Themen auffuellen, sondern die
    # Luecke klar melden und nur die vorhandenen Fragen speichern.
    if len(eintraege) < ANZAHL:
        print(
            f"Warnung: nur {len(eintraege)} statt {ANZAHL} Afrika-Fragen gefunden. "
            f"Es wird NICHT mit anderen Themen aufgefuellt.",
            file=sys.stderr,
        )

    # ensure_ascii=False, damit Umlaute/Sonderzeichen lesbar bleiben.
    with open("markets.json", "w", encoding="utf-8") as datei:
        json.dump(eintraege, datei, ensure_ascii=False, indent=2)

    print(f"{len(eintraege)} Afrika-Fragen in markets.json gespeichert.")
    for m in afrika:
        print(f"  [{land_von_market(m)}] p={hole_market_p(m)}  {m['question']}")


if __name__ == "__main__":
    main()
