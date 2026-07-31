"""fetch_markets.py

Laedt offene Fragen aus allen angebundenen Quellen (Polymarket, Metaculus)
und speichert eine Auswahl als markets.json.

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
from datetime import datetime, timezone

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

# Einzelne Fragen, die alle Regeln erfuellen und trotzdem nicht auf die Seite
# gehoeren. Bewusst eine namentliche Liste und keine neue Filterregel: der
# Grund ist jeweils inhaltlich und laesst sich nicht verallgemeinern, ohne
# nebenbei brauchbare Fragen mitzunehmen.
#
# Jeder Eintrag braucht eine Begruendung. Eine Ausschlussliste ohne Gruende
# waere nach drei Monaten nicht mehr pruefbar und wuerde stillschweigend
# weiterwirken.
AUSGESCHLOSSEN = {
    # Scherzmarkt ueber einen US-Politiker. Der Afrika-Bezug ist zufaellig,
    # das Stichwort "Sudan" steht nur im Nebensatz. Neben Hungersnot- und
    # Waffenstillstandsfragen wirkt die Frage deplatziert.
    "polymarket-1986523": "Scherzfrage, Afrika-Bezug nur nominell",
}

# Mindestliquiditaet je Quelle. Gilt NUR fuer Fragen, die auch eine
# Vergleichszahl haben: wo es keinen Benchmark gibt, kann er auch nicht
# uninformativ sein. Eine Metaculus-Frage ohne Community-Median bleibt also
# unabhaengig von ihrer Beteiligung drin - dort zaehlt nur der Forecast.
#
# Polymarket, Einheit ist Handelsvolumen in Dollar. Der Wert lag zuerst bei
# 5'000, dann 1'200 und jetzt bei 250 - jede Senkung war eine Entscheidung
# gegen Sauberkeit und fuer Anzahl, weil es zu Afrika schlicht wenige Fragen
# mit Preis gibt.
#
# Die Verteilung der offenen Afrika-Fragen (31.07.2026): neun ab 11'264,
# vier zwischen 1'399 und 2'142, der Rest zwischen 24 und 1'141. Bei 250
# fallen nur noch die aeussersten weg. Ein Preis aus 300 Dollar Umsatz steht
# dort, wo zufaellig zuletzt jemand gehandelt hat, und ist keine
# Marktmeinung.
#
# Der Ausgleich dafuer steht auf der Seite: jede Frage zeigt ihr
# Handelsvolumen. Wer "1%" neben "300 USD traded" sieht, kann den Wert selbst
# einordnen - das ist ehrlicher, als die Frage stillschweigend wegzulassen
# oder den duennen Preis wortlos wie einen belastbaren zu zeigen.
#
# Metaculus, Einheit ist Zahl der Prognostiker. Der Wert ist VORLAEUFIG und
# ungetestet: solange der Community-Median gesperrt ist, greift die Regel dort
# nie. Beobachtete Beteiligung liegt bei 0 bis 144 (Median 9). Sobald die
# Zugriffsstufe steht, gehoert er an echten Daten geprueft.
MIN_LIQUIDITAET = {
    "polymarket": 250,
    "metaculus": 15,
}

# Nur Fragen aufnehmen, die eine Vergleichszahl haben. Jede Karte zeigt dann
# drei Zahlen statt zwei, und der Vergleich Modell gegen Benchmark - der Zweck
# des Projekts - gilt fuer jede einzelne Frage.
#
# Der Preis ist hoch und sollte bewusst getragen werden: Metaculus faellt
# damit vollstaendig weg, weil unsere Zugriffsstufe den Community-Median
# sperrt (siehe source_metaculus.py). Es bleiben nur Polymarket-Fragen, und
# davon gibt es zu Afrika wenige. Auf False gesetzt kommen Fragen ohne
# Vergleichszahl wieder dazu, begrenzt durch MAX_OHNE_BENCHMARK.
NUR_MIT_BENCHMARK = True

# Obergrenze fuer Fragen OHNE Vergleichszahl. Betrifft derzeit nur Metaculus:
# der Community-Median ist fuer unser Konto gesperrt, die Fragen sind aber
# trotzdem wertvoll, weil Claude sie prognostizieren kann. Eine Karte ohne
# Vergleichszahl zeigt eben nur den Forecast - besser als keine Frage.
# Begrenzt, damit diese Fragen die Seite nicht dominieren und der
# Forecast-Lauf bezahlbar bleibt.
MAX_OHNE_BENCHMARK = 15

# Fragen ohne Vergleichszahl nehmen wir nur aus diesen Kategorien auf:
# Wirtschaft und Politik. Ohne Benchmark ist der Forecast die einzige Aussage
# der Karte, und die soll zum Thema des Projekts passen - ein Ebola-Fall oder
# eine Sportfrage gehoert dann nicht dazu.
KATEGORIEN_OHNE_BENCHMARK = ("elections", "security", "diplomacy", "economy", "other")

# Zeithorizont fuer Fragen ohne Vergleichszahl, in Tagen. Metaculus fuehrt
# Fragen mit sehr fernem Aufloesungsdatum ("Will X be elected President of
# South Africa before 2065?"). Eine Prognose, deren Ausgang in 39 Jahren
# feststeht, ist auf einem Dashboard wertlos: sie laesst sich nie ueberpruefen
# und verdraengt eine Frage, die naechsten Monat faellig ist.
MAX_HORIZONT_TAGE = 1460   # rund vier Jahre

# Alle angebundenen Quellen. Metaculus liefert Fragen, aber keinen
# Community-Median: der ist fuer unsere Zugriffsstufe gesperrt. Solche Fragen
# kommen ohne Vergleichszahl auf die Seite, begrenzt durch MAX_OHNE_BENCHMARK.
QUELLEN = [
    source_polymarket,
    source_metaculus,
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
        # Humanitaere Folgen bewaffneter Konflikte. Metaculus fragt haeufiger
        # danach als Polymarket, und eine IPC-Hungersnotklassifikation im
        # Sudan gehoert naeher an Sicherheit als an "other".
        "famine", "food insecurity", "ipc ", "displac", "refugee",
        "humanitarian", "excess mortality",
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
        # Restitution ist eine zwischenstaatliche Frage, keine kulturelle
        # Randnotiz: die Benin-Bronzen sind seit Jahren Gegenstand
        # bilateraler Verhandlungen zwischen Nigeria und Grossbritannien.
        "restitution", "repatriat",
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


def loest_noch_auf(frage):
    """True, wenn die Aufloesung noch bevorsteht.

    Fragen, deren Aufloesungsdatum verstrichen ist, sind keine Prognosefragen
    mehr. Beobachtet: die aethiopische Wahl fand am 1. Juni 2026 statt, Abiy
    Ahmed gewann, und der Polymarket-Markt stand 59 Tage spaeter immer noch
    auf closed=false, weil das Orakel nicht abgerechnet hatte. Beide Modelle
    "prognostizierten" die Frage daraufhin mit 0.99 und 0.80 - sie lasen das
    Ergebnis nach, sie schaetzten nicht.

    Solche Fragen wuerden allen Beteiligten glaenzende Brier Scores bescheren
    fuer etwas, das niemand prognostiziert hat. Der Snapshot-Mechanismus
    schuetzt davor nicht: er misst am fruehesten Zeitpunkt MIT Prognose, aber
    auch die entstand nach dem Ereignis.

    Fehlt oder verunglueckt das Datum, bleibt die Frage drin - lieber eine
    Frage zu viel als eine stillschweigend verworfene.

    Bekannte Luecke: eine Frage, deren Ereignis bereits eingetreten ist, deren
    Aufloesungsdatum aber noch in der Zukunft liegt, faellt hier nicht auf.
    Das Datum ist das einzige Signal, das die Quellen dazu hergeben.
    """
    zeit = frage.get("resolve_time") or ""
    if not zeit:
        return True

    try:
        ziel = datetime.fromisoformat(zeit.replace("Z", "+00:00"))
    except ValueError:
        return True

    return ziel > datetime.now(timezone.utc)


def hat_genug_liquiditaet(frage):
    """True, wenn die Vergleichszahl der Frage belastbar genug ist.

    Der Punkt ist nicht die Frage, sondern ihr Benchmark: eine Quote, die aus
    90 Dollar Handelsvolumen entsteht, sagt nichts ueber die Wahrscheinlichkeit
    aus - sie steht dort, wo zufaellig zuletzt jemand gehandelt hat. Auf der
    Seite erschiene sie trotzdem als "Markt sagt 0 Prozent", und im Brier Score
    wuerde sie spaeter zaehlen, als waere sie eine ernsthafte Schaetzung.

    Fragen OHNE Vergleichszahl bleiben immer drin: dort gibt es keinen
    Benchmark, der uninformativ sein koennte, und die Karte zeigt ohnehin nur
    die Modellprognosen.
    """
    if frage.get("market_p") is None:
        return True

    schwelle = MIN_LIQUIDITAET.get(frage.get("source"))
    if schwelle is None:
        return True          # unbekannte Quelle: nicht aussperren

    return frage.get("volume", 0.0) >= schwelle


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


def aufloesung_zuerst(frage):
    """Sortierschluessel: fruehe Aufloesung zuerst, Fragen ohne Datum zuletzt.

    Fuer Fragen ohne Vergleichszahl ist das die sinnvollste Reihenfolge. Was
    bald aufgeloest wird, laesst sich bald ueberpruefen - und eine Prognose,
    deren Ausgang man in Wochen kennt, ist mehr wert als eine, die 2031
    faellig wird. Die Zeitangaben sind ISO-Text ("2026-09-10T09:00:00Z"), der
    sich lexikografisch korrekt sortieren laesst.
    """
    zeit = frage.get("resolve_time") or ""
    # Leerer Text sortiert vor allen Datumsangaben, darum explizit ans Ende.
    return (1, "") if not zeit else (0, zeit)


def loest_bald_auf(frage):
    """True, wenn die Frage innerhalb von MAX_HORIZONT_TAGE aufgeloest wird.

    Fragen ohne Datum lassen wir durch: fehlende Angabe ist kein Grund, eine
    sonst passende Frage zu verwerfen. Unlesbare Datumsangaben ebenso - lieber
    eine Frage zu viel als ein Absturz an einem Formatfehler.
    """
    zeit = frage.get("resolve_time") or ""
    if not zeit:
        return True

    try:
        ziel = datetime.fromisoformat(zeit.replace("Z", "+00:00"))
    except ValueError:
        return True

    return (ziel - datetime.now(timezone.utc)).days <= MAX_HORIZONT_TAGE


def waehle_ohne_benchmark(nach_quelle, gewaehlt, gesehene_events):
    """Nimmt bis zu MAX_OHNE_BENCHMARK Fragen ohne Vergleichszahl auf.

    Eigener Durchlauf, weil diese Fragen in den beiden anderen durchs Raster
    fielen: ist_moderat() ist ohne Quote falsch, und die Sortierung nach
    hoechster Quote schiebt sie ans Ende. Massgeblich ist hier stattdessen die
    Naehe der Aufloesung.
    """
    kandidaten = []
    for fragen in nach_quelle.values():
        kandidaten.extend(
            f for f in fragen
            if f.get("market_p") is None
            and bestimme_kategorie(f) in KATEGORIEN_OHNE_BENCHMARK
            and loest_bald_auf(f)
        )

    kandidaten.sort(key=aufloesung_zuerst)

    genommen = 0
    for frage in kandidaten:
        if genommen == MAX_OHNE_BENCHMARK or len(gewaehlt) == ANZAHL:
            break
        if frage.get("event_id") in gesehene_events:
            continue
        gesehene_events.add(frage.get("event_id"))
        gewaehlt.append(frage)
        genommen += 1

    return genommen


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
    afrika_je_quelle = {}
    moderate = {}
    extreme = {}
    for name, fragen in nach_quelle.items():
        alle_afrika = [f for f in fragen
                       if hat_afrika_bezug(f) and f["id"] not in AUSGESCHLOSSEN]

        # Zwei Ausschluesse vor jeder weiteren Auswahl. Sonst konkurrierten
        # unbrauchbare Fragen um Plaetze, die eine belastbare besser fuellt.
        noch_offen = [f for f in alle_afrika if loest_noch_auf(f)]
        ueberfaellig = len(alle_afrika) - len(noch_offen)

        afrika = [f for f in noch_offen if hat_genug_liquiditaet(f)]
        zu_duenn = len(noch_offen) - len(afrika)
        afrika_je_quelle[name] = afrika

        mit_quote = [f for f in afrika if f.get("market_p") is not None]

        moderate[name] = [f for f in mit_quote if ist_moderat(f)]
        moderate[name].sort(key=lambda f: f.get("volume", 0.0), reverse=True)

        extreme[name] = [f for f in mit_quote if not ist_moderat(f)]
        extreme[name].sort(key=quote_absteigend, reverse=True)

        anzahl_events = len({f.get("event_id") for f in afrika})
        ohne_quote = len(afrika) - len(mit_quote)
        gruende = []
        if ueberfaellig:
            gruende.append(f"{ueberfaellig} ueberfaellig")
        if zu_duenn:
            gruende.append(f"{zu_duenn} zu duenne Vergleichszahl")
        hinweis = f", verworfen: {', '.join(gruende)}" if gruende else ""
        print(f"  {name}: {len(afrika)} Fragen mit Afrika-Bezug "
              f"aus {anzahl_events} Events "
              f"({len(moderate[name])} mit moderater Quote, "
              f"{ohne_quote} ohne Vergleichszahl{hinweis}).")

    gewaehlt = []
    gesehene_events = set()

    # Reihenfolge nach Wert: Fragen MIT Vergleichszahl zuerst, denn nur dort
    # entsteht der eigentliche Vergleich Modell gegen Markt. Fragen ohne
    # Vergleichszahl fuellen danach auf.
    waehle_reihum(moderate, gewaehlt, gesehene_events)   # 1. bevorzugt
    waehle_reihum(extreme, gewaehlt, gesehene_events)    # 2. Notnagel

    if NUR_MIT_BENCHMARK:
        ohne_moeglich = sum(
            1 for fragen in afrika_je_quelle.values()
            for f in fragen if f.get("market_p") is None
        )
        if ohne_moeglich:
            print(f"  {ohne_moeglich} Fragen ohne Vergleichszahl nicht "
                  f"aufgenommen (NUR_MIT_BENCHMARK).")
        return gewaehlt

    ohne = waehle_ohne_benchmark(afrika_je_quelle, gewaehlt, gesehene_events)

    if ohne:
        print(f"  dazu {ohne} Fragen ohne Vergleichszahl "
              f"(Obergrenze {MAX_OHNE_BENCHMARK}, naechste Aufloesung zuerst).")

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
        "resolve_time": frage.get("resolve_time", ""),
        "description": frage.get("description", ""),
        "url": frage.get("url", ""),
        # Handelsvolumen kommt mit auf die Seite. Die Schwelle liegt niedrig,
        # damit moeglichst viele Fragen mit Zahl erscheinen; dann muss aber
        # sichtbar sein, worauf ein Preis ruht. 24 Dollar Umsatz neben "1%" zu
        # zeigen ist ehrlicher, als die Frage stillschweigend wegzulassen.
        "volume": frage.get("volume", 0.0),
    }


# --- Hauptablauf -----------------------------------------------------------

def quellen_zaehlung(eintraege):
    """Zaehlt, wie viele Fragen je Quelle in einer Eintragsliste stehen."""
    zaehler = {}
    for eintrag in eintraege:
        name = eintrag.get("source", "unknown")
        zaehler[name] = zaehler.get(name, 0) + 1
    return zaehler


def quelle_verschwunden(neu, alt, erwartet_leer=()):
    """Gibt die Quellen zurueck, die vorher Fragen hatten und jetzt keine mehr.

    Der Schutz "schreibe nichts, wenn gar keine Frage da ist" reichte nicht:
    faellt EINE von mehreren Quellen aus, kommen immer noch Fragen zusammen,
    und die Datei wird ueberschrieben - die Fragen der ausgefallenen Quelle
    verschwinden dann stillschweigend von der Seite. Genau das ist beim ersten
    Lauf der GitHub Action passiert (Metaculus lieferte nichts, die Seite fiel
    von 18 auf 12 Karten).

    erwartet_leer nennt Quellen, deren Ausbleiben eine Folge unserer eigenen
    Regeln ist und kein Ausfall. Ohne diese Unterscheidung haette das
    Einschalten von NUR_MIT_BENCHMARK wie ein Metaculus-Ausfall ausgesehen und
    den Lauf blockiert - die Warnung waere richtig gewesen und trotzdem falsch.

    Eine Quelle, die noch nie etwas geliefert hat, faellt hier nicht auf - das
    ist richtig so, sonst wuerde jeder noch nicht angebundene Platzhalter den
    Lauf blockieren.
    """
    neu_zaehler = quellen_zaehlung(neu)
    return [name for name, anzahl in quellen_zaehlung(alt).items()
            if anzahl > 0
            and neu_zaehler.get(name, 0) == 0
            and name not in erwartet_leer]


def lade_vorherige():
    """Liest die bestehende markets.json, oder eine leere Liste."""
    try:
        with open(MARKETS_DATEI, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


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

    # Eine Quelle, die bisher lieferte und jetzt schweigt, ist fast immer ein
    # Ausfall (Token fehlt, API gesperrt, Rate Limit) und fast nie die
    # Wahrheit. Wir schreiben dann NICHT, damit die betroffenen Fragen nicht
    # stillschweigend von der Seite fallen, und melden es deutlich.
    # Quellen, die nur Fragen ohne Vergleichszahl liefern, fehlen bei
    # NUR_MIT_BENCHMARK erwartungsgemaess und sind kein Ausfall.
    if NUR_MIT_BENCHMARK:
        erwartet_leer = {name for name, fragen in nach_quelle.items()
                         if all(f.get("market_p") is None for f in fragen)}
    else:
        erwartet_leer = set()

    fehlend = quelle_verschwunden(eintraege, lade_vorherige(), erwartet_leer)
    if fehlend:
        print(
            f"Fehler: {', '.join(fehlend)} lieferte(n) diesmal nichts, vorher "
            f"schon. Das sieht nach einem Ausfall aus (fehlendes Token, "
            f"gesperrte API, Rate Limit), nicht nach einer echten Aenderung.\n"
            f"{MARKETS_DATEI} wird NICHT ueberschrieben - sonst verschwaenden "
            f"diese Fragen unbemerkt von der Seite. Bitte die Meldungen der "
            f"Quelle weiter oben pruefen.",
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
    # Die Windows-Konsole arbeitet standardmaessig mit cp1252. Fragetexte
    # koennen Emojis enthalten (bei Metaculus regelmaessig), und die lassen
    # jede Ausgabe mit UnicodeEncodeError abstuerzen - mitten im Lauf, nach
    # dem Laden aller Fragen. errors="replace" macht daraus ein Fragezeichen.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    main()
