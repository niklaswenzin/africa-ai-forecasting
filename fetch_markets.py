"""fetch_markets.py

Laedt offene Fragen aus allen angebundenen Quellen (Polymarket, Metaculus,
Kalshi) und speichert eine Auswahl als markets.json.

Design: Fragen mit Afrika-Bezug, maximal eine pro Land, keine Sport-Fragen.
Bevorzugt werden Fragen mit einer Quote zwischen 0.05 und 0.95; Extremwerte
nur, falls sonst nicht genug zusammenkommen. Die Auswahl laeuft reihum ueber
die Quellen, damit eine grosse Quelle nicht alle Plaetze belegt. Bleiben nach
allen Filtern weniger als ANZAHL uebrig, speichern wir alle vorhandenen und
melden die Luecke, statt mit anderen Themen aufzufuellen.

Jede Quelle liegt in einer eigenen Datei und stellt eine Funktion
lade_fragen() bereit, die Eintraege in diesem gemeinsamen Format liefert:
id, source, question, market_p, benchmark_type, description, volume.
Eine neue Quelle anzubinden heisst darum: eine Datei schreiben und sie unten
in QUELLEN eintragen. Filter und Auswahl gelten dann automatisch auch fuer sie.
"""

import json
import re
import sys

import source_kalshi
import source_metaculus
import source_polymarket

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"

# Obergrenze, nicht Sollwert. Wie viele Fragen tatsaechlich zusammenkommen,
# haengt daran, wie viele eigenstaendige Ereignisse die Quellen gerade
# hergeben. Realistisch liefert Polymarket derzeit rund 13 (die ~46 Treffer
# mit Afrika-Bezug sind groesstenteils Kandidatenvarianten derselben Wahlen).
ANZAHL = 30

MODERAT_MIN = 0.05         # bevorzugte Quote: nicht extremer als diese Grenzen
MODERAT_MAX = 0.95

# Alle angebundenen Quellen. Metaculus und Kalshi geben derzeit leere Listen
# zurueck (siehe die jeweiligen Dateien), die Pipeline laeuft trotzdem durch.
QUELLEN = [
    source_polymarket,
    source_metaculus,
    source_kalshi,
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
# "sudan" greift; land_von_frage nimmt das erste passende Keyword.
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

# Sport-Begriffe: matcht einer davon, verwerfen wir die Frage als Afrika-Frage.
# Grund: Laendernamen tauchen auch in Sport-Fragen auf (z. B. Cricket "T20
# Namibia ... vs Uganda"). Die APIs liefern keine verlaessliche Kategorie:
# geprueft wurden events[0].countryName, electionType und series - fuer
# Sportfragen sind alle drei leer. Darum diese Negativliste als Ersatz.
#
# Sie ist unvollstaendig und bleibt es. "Will Renaissance Zemamra win Morocco
# Botola Pro?" ist durchgerutscht, weil die marokkanische Fussballliga
# "Botola Pro" heisst und keines der alten Stichworte enthielt. Neue Lecks
# gehoeren hier ergaenzt.
#
# Bewusst NICHT aufgenommen, weil sie politische Fragen faelschlich treffen
# wuerden: "final" (zweiter Wahlgang, "final round"), "premier" (Premier als
# Regierungschef), "race" (Wahlkampf), "win"/"winner" (jede Wahlfrage).
SPORT_KEYWORDS = [
    # Ligen und Wettbewerbe
    "cricket", "cup", "league", "botola", "afcon", "fifa", "uefa", "caf ",
    "nba", "nfl", "mlb", "serie a", "la liga", "bundesliga",
    # Sportarten
    "football", "soccer", "basketball", "rugby", "tennis", "boxing", "golf",
    "olympic", "athletics", "marathon",
    # Spielbetrieb
    "t20", "odi", "tournament", "quadrangular", " vs ", "vs.", " fc ",
    "match", "relegation", "top scorer", "playoff",
]


# Kategorien fuer die Tab-Leiste auf der Seite. Die Reihenfolge in dieser Liste
# ist die Pruefreihenfolge und damit inhaltlich entscheidend, nicht bloss
# kosmetisch: die erste passende Kategorie gewinnt.
#
# security steht vorn, weil Fragen wie "Wahl nach dem Putsch in Guinea-Bissau"
# beide Wortfelder treffen. Der Putsch ist dort das bestimmende Ereignis, die
# Wahl nur sein Gegenstand - solche Fragen gehoeren unter security.
# economy steht hinten, weil Begriffe wie "trade" oder "deal" auch in
# politischen Fragen vorkommen und sonst zu viel einsammeln wuerden.
#
# Teilstring-Suche, nicht Wortgrenzen: so greift "elect" auch in "election",
# "elections", "electoral" und "re-elect", ohne dass jede Form aufgelistet
# werden muss.
KATEGORIE_KEYWORDS = [
    ("security", [
        "war", "coup", "ceasefire", "conflict", "militant", "insurgen",
        "rebel", "junta", "terror", "attack", "invasion", "troops",
        "military", "violence", "unrest", "hostage", "genocide",
    ]),
    ("elections", [
        "elect", "president", "parliament", "vote", "ballot", "candidate",
        "prime minister", "seats", "referendum", "poll", "inaugurat",
    ]),
    ("economy", [
        "gdp", "inflation", "imf", "world bank", "currency", "trade",
        "debt", "default", "tariff", "export", "import", "oil price",
        "central bank", "interest rate", "recession", "bailout", "budget",
    ]),
    # Diplomatie steht hinter economy, weil "trade deal" beide Wortfelder
    # trifft und ein Handelsabkommen naeher an Wirtschaft liegt als an
    # Aussenpolitik. Bewusst getrennt von security: ein Normalisierungs-
    # abkommen ist keine Konfliktfrage, und die Kategorie security soll
    # aussagekraeftig bleiben, wenn spaeter echte Konfliktfragen dazukommen.
    ("diplomacy", [
        "abraham accords", "recognize", "recognise", "diplomatic",
        "normalizat", "normalisat", "embassy", "treaty", "accord",
        "summit", "sanction", "join the", "membership", "alliance",
    ]),
]

KATEGORIE_STANDARD = "other"   # wenn keine Regel greift


# --- Quellen abfragen ------------------------------------------------------

def lade_alle_quellen():
    """Ruft jede Quelle auf und gibt ein Dict quellenname -> Fragen zurueck.

    Faellt eine Quelle mit einem Fehler aus, soll das die uebrigen nicht
    mitreissen: wir melden den Ausfall und machen mit den anderen weiter.
    Ein leeres Ergebnis ist ausdruecklich erlaubt (noch nicht angebundene
    Quellen geben genau das zurueck).
    """
    nach_quelle = {}
    for quelle in QUELLEN:
        name = quelle.QUELLE
        try:
            nach_quelle[name] = quelle.lade_fragen()
        except Exception as fehler:
            # Fehlertyp mit ausgeben: "IndexError: list index out of range"
            # verraet einen Bug im eigenen Code, "ConnectionError" einen
            # echten Ausfall der Gegenstelle. Ohne den Typ sieht beides gleich aus.
            print(f"  Warnung: Quelle {name} ausgefallen "
                  f"({type(fehler).__name__}: {fehler}), wird uebersprungen.",
                  file=sys.stderr)
            nach_quelle[name] = []
    return nach_quelle


# --- Hilfsfunktionen fuer die Auswahl -------------------------------------

def enthaelt_wort(frage, keywords):
    """Prueft, ob eines der Keywords als ganzes Wort im Fragetext steht.

    Wortgrenzen (nicht bloss Teilstring), damit "niger" nicht in "Nigeria" und
    "mali" nicht in "Somalia" faelschlich anschlaegt. Mehrwort-Phrasen wie
    "south africa" funktionieren damit ebenfalls.
    """
    text = frage.get("question", "").lower()
    for wort in keywords:
        # (?<![a-z]) und (?![a-z]): links und rechts kein weiterer Buchstabe.
        if re.search(r"(?<![a-z])" + re.escape(wort) + r"(?![a-z])", text):
            return True
    return False


def enthaelt_teilstring(frage, keywords):
    """Prueft, ob eines der Keywords als Teilstring im Fragetext steht.

    Fuer Sport-Begriffe wie " vs " oder "t20", die keine Wortgrenzen brauchen.
    """
    text = frage.get("question", "").lower()
    return any(wort in text for wort in keywords)


def ist_sport(frage):
    """True, wenn die Frage nach Sport aussieht (Cricket, Cup, "vs" usw.)."""
    return enthaelt_teilstring(frage, SPORT_KEYWORDS)


def hat_afrika_bezug(frage):
    """True, wenn ein Afrika-Keyword vorkommt UND es keine Sport-Frage ist."""
    return enthaelt_wort(frage, AFRIKA_KEYWORDS) and not ist_sport(frage)


def land_von_frage(frage):
    """Gibt das Land der Frage zurueck (erstes passendes Keyword aus AFRIKA_LAND).

    Reihenfolge im Dict sorgt dafuer, dass spezifische Keywords zuerst greifen
    (z. B. "south sudan" vor "sudan"). Fehlt ein Treffer, nehmen wir die id als
    eigenes Land, damit so eine Frage nie faelschlich mit einer anderen
    zusammenfaellt.

    Das Land gilt quellenuebergreifend: fragen dieselbe Frage auf Polymarket
    und Kalshi nach Kenia, nehmen wir nur eine davon.
    """
    text = frage.get("question", "").lower()
    for wort, land in AFRIKA_LAND.items():
        if re.search(r"(?<![a-z])" + re.escape(wort) + r"(?![a-z])", text):
            return land
    return frage.get("id")


def bestimme_kategorie(frage):
    """Ordnet eine Frage einer der Kategorien zu: elections, economy, security, other.

    Zwei Stufen. Erstens der Hinweis der Quelle: Polymarket markiert Wahlfragen
    ueber das Feld electionType, und wo die API es selbst weiss, raten wir nicht
    nach. Zweitens, und nur wenn kein Hinweis vorliegt, die Keyword-Regeln in
    der Reihenfolge von KATEGORIE_KEYWORDS.

    Gesucht wird in Fragetext UND Event-Titel. Der Event-Titel traegt oft den
    Zusammenhang, den die einzelne Frage weglaesst: "Will X win the most seats?"
    allein sagt nichts, das zugehoerige Event heisst aber "Zambia National
    Assembly Election Winner".
    """
    hinweis = frage.get("category_hint")
    if hinweis:
        return hinweis

    text = (frage.get("question", "") + " " + frage.get("event_title", "")).lower()

    for kategorie, keywords in KATEGORIE_KEYWORDS:
        if any(wort in text for wort in keywords):
            return kategorie

    return KATEGORIE_STANDARD


def ist_moderat(frage):
    """True, wenn die Quote existiert und nicht extrem ist (zwischen den Grenzen)."""
    p = frage.get("market_p")
    return p is not None and MODERAT_MIN <= p <= MODERAT_MAX


def quote_absteigend(frage):
    """Sortierschluessel fuer den Extremwert-Durchlauf: hoechste Quote zuerst.

    Bei einer Wahl mit sieben Kandidaten sind oft alle Quoten extrem: sechs
    Aussenseiter nahe 0 und ein Favorit nahe 1. Wir wollen den Favoriten, denn
    nur bei ihm sagt die Karte etwas aus - bei einem Aussenseiter sind sich
    Markt und Modell einig, dass nichts passiert.

    Nach Volumen zu sortieren traf einen beliebigen Aussenseiter. Nach Abstand
    zu 0.5 zu sortieren ebenfalls, denn |0.042 - 0.5| ist knapp kleiner als
    |0.96 - 0.5|: ein symmetrisches Mass haelt "fast sicher nein" und "fast
    sicher ja" faelschlich fuer gleich informativ. Darum schlicht die hoechste
    Quote. Fehlt sie, kommt die Frage ganz nach hinten.
    """
    p = frage.get("market_p")
    return p if p is not None else -1.0


# --- Auswahl ---------------------------------------------------------------

def naechste_passende(kandidaten, gesehene_events):
    """Gibt die erste Frage zurueck, deren Event noch nicht vertreten ist.

    Die Kandidatenlisten sind bereits nach Volumen sortiert, die erste
    passende ist also zugleich die aktivste Frage ihres Events.
    """
    for frage in kandidaten:
        if frage.get("event_id") not in gesehene_events:
            return frage
    return None


def waehle_reihum(nach_quelle, gewaehlt, gesehene_events):
    """Nimmt reihum aus jeder Quelle die naechste passende Frage.

    Reihum statt "beste zuerst", damit eine grosse Quelle wie Polymarket nicht
    alle Plaetze belegt und kleinere Quellen sichtbar bleiben. Kann eine Quelle
    nichts mehr beitragen, wird sie einfach uebersprungen - ihr Anteil geht
    dann an die uebrigen. Die Funktion arbeitet auf den uebergebenen Listen
    weiter, damit ein erster Durchlauf (moderate Quoten) und ein zweiter
    (Extremwerte) sich nicht in die Quere kommen.
    """
    while len(gewaehlt) < ANZAHL:
        etwas_genommen = False

        for kandidaten in nach_quelle.values():
            if len(gewaehlt) == ANZAHL:
                break

            frage = naechste_passende(kandidaten, gesehene_events)
            if frage is None:
                continue  # diese Quelle hat gerade nichts Passendes

            kandidaten.remove(frage)
            gesehene_events.add(frage.get("event_id"))
            gewaehlt.append(frage)
            etwas_genommen = True

        # Eine komplette Runde ohne Treffer heisst: keine Quelle kann mehr.
        if not etwas_genommen:
            break


def waehle_fragen(nach_quelle):
    """Waehlt bis zu ANZAHL Fragen: max. eine pro Event, kein Sport, reihum.

    Frueher galt "maximal eine Frage pro Land". Das war fuer 5 Plaetze gedacht
    und zu streng: Kenia und Nigeria haben mehrere unabhaengige Fragen, die
    alle interessant sind. Massgeblich ist jetzt das Event. Damit sind mehrere
    Fragen pro Land erlaubt, aber nicht zwoelf Kandidatenvarianten derselben
    Wahl - die haengen bei Polymarket alle am selben Event.

    Bevorzugt Quoten zwischen MODERAT_MIN und MODERAT_MAX (erster Durchlauf).
    Nur wenn so nicht genug zusammenkommen, sind Extremwerte erlaubt (zweiter
    Durchlauf). Innerhalb jeder Quelle entscheidet das Volumen.
    """
    # Pro Quelle: nur Afrika-Fragen, aufgeteilt in moderate und extreme Quoten.
    # Die beiden Listen werden unterschiedlich sortiert, weil "die beste Frage"
    # in beiden Faellen etwas anderes heisst:
    #   moderate -> nach Volumen, das aktivste Marktgeschehen zuerst.
    #   extreme  -> nach hoechster Quote, damit bei einer Wahl der Favorit
    #               gewinnt und nicht ein beliebiger Aussenseiter mit 0.4%.
    moderate = {}
    extreme = {}
    for name, fragen in nach_quelle.items():
        afrika = [f for f in fragen if hat_afrika_bezug(f)]

        moderate[name] = [f for f in afrika if ist_moderat(f)]
        moderate[name].sort(key=lambda f: f.get("volume", 0.0), reverse=True)

        extreme[name] = [f for f in afrika if not ist_moderat(f)]
        extreme[name].sort(key=quote_absteigend, reverse=True)
        anzahl_events = len({f.get("event_id") for f in afrika})
        print(f"  {name}: {len(afrika)} Fragen mit Afrika-Bezug "
              f"aus {anzahl_events} Events "
              f"({len(moderate[name])} Fragen mit moderater Quote).")

    gewaehlt = []
    gesehene_events = set()
    waehle_reihum(moderate, gewaehlt, gesehene_events)  # 1. bevorzugt
    waehle_reihum(extreme, gewaehlt, gesehene_events)   # 2. Notnagel
    return gewaehlt


# --- Eintrag bauen ---------------------------------------------------------

def baue_eintrag(frage):
    """Macht aus einer ausgewaehlten Frage den Eintrag fuer markets.json.

    "volume" brauchen wir nur fuer die Auswahl und lassen es hier weg.
    "description" enthaelt die Aufloesungskriterien (keine Quote) und wird
    spaeter in forecast.py in den Prompt gegeben, damit das Modell die
    formalen Bedingungen kennt.
    """
    return {
        "id": frage["id"],
        "source": frage["source"],
        "question": frage["question"],
        "market_p": frage["market_p"],
        "benchmark_type": frage["benchmark_type"],
        "africa": True,
        "country": land_von_frage(frage),
        "category": bestimme_kategorie(frage),
        "event_id": frage.get("event_id"),
        "event_title": frage.get("event_title", ""),
        "description": frage.get("description", ""),
    }


# --- Hauptablauf -----------------------------------------------------------

def main():
    print(f"Quellen abfragen ({len(QUELLEN)}):")
    nach_quelle = lade_alle_quellen()

    print("Auswahl:")
    gewaehlt = waehle_fragen(nach_quelle)
    print(f"{len(gewaehlt)} Fragen gewaehlt (max. eine pro Event, kein Sport).")

    eintraege = [baue_eintrag(f) for f in gewaehlt]

    # Gar keine Frage? Dann die bestehende markets.json NICHT ueberschreiben.
    # Sonst zerstoert ein einzelner Ausfall aller Quellen den letzten guten
    # Stand, und die Folgeskripte laufen ins Leere. Lieber klar abbrechen und
    # die alte Datei behalten.
    if not eintraege:
        print(
            f"Fehler: keine einzige Frage gefunden. {MARKETS_DATEI} wird NICHT "
            f"ueberschrieben, der letzte Stand bleibt erhalten.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ANZAHL ist eine Obergrenze, kein Sollwert: wie viele Fragen es werden,
    # haengt daran, wie viele eigenstaendige Ereignisse es gerade gibt. Weniger
    # als ANZAHL ist darum der Normalfall und keine Warnung wert. Aufgefuellt
    # wird nie mit fachfremden Themen.
    if len(eintraege) < ANZAHL:
        print(f"Hinweis: {len(eintraege)} Fragen (Obergrenze {ANZAHL}). "
              f"Mehr eigenstaendige Ereignisse gibt es derzeit nicht.")

    # ensure_ascii=False, damit Umlaute/Sonderzeichen lesbar bleiben.
    with open(MARKETS_DATEI, "w", encoding="utf-8") as datei:
        json.dump(eintraege, datei, ensure_ascii=False, indent=2)

    print(f"{len(eintraege)} Fragen in {MARKETS_DATEI} gespeichert.")
    for e in eintraege:
        print(f"  [{e['source']}] p={e['market_p']}  {e['question']}")


if __name__ == "__main__":
    main()
