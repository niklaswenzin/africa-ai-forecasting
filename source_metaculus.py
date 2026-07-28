"""source_metaculus.py

Quelle Metaculus. Liefert offene binaere Fragen mit dem Median der
Community-Prognosen im gemeinsamen Format.

Was verifiziert ist
-------------------
Direkt gegen die API geprueft (2026-07-28):
- Basis https://www.metaculus.com, Endpoint /api/posts/ existiert.
- JEDER Zugriff braucht ein Token. Ohne Token antwortet die API mit
  HTTP 403 "The API is only available to authenticated users". Das gilt auch
  fuer /api/schema/, /api/docs/ und die alte /api2/-Route.
- Header-Format laut Doku: "Authorization: Token <token>".

Mit Token verifiziert (2026-07-28)
---------------------------------
- Antwort: {"next", "previous", "results"}, Paginierung ueber limit/offset.
- Aufloesungskriterien: question.resolution_criteria.
- Zahl der Prognostiker: nr_forecasters, auf OBERSTER Ebene, nicht in question.
- Strukturierte Kategorie: projects.category[0].slug. Verifiziert gesehen:
  "economy-business". Weitere Slugs sind unbekannt und fallen auf die
  Keyword-Regeln in fetch_markets.py zurueck - ein unbekannter Slug liefert
  also keinen falschen Hinweis, sondern gar keinen.
- Community-Median: question.aggregations.recency_weighted.latest. Der Pfad
  existiert im Schema.

BLOCKIERT: der Median ist fuer dieses Konto durchgehend null
------------------------------------------------------------
Gemessen ueber 600 offene binaere Fragen: 0 mit sichtbarem Median. Kein
Parameter schaltet ihn frei (with_cp, include_cp, aggregation_methods wurden
geprueft), auch der Detail-Endpoint liefert latest = null.

Ursache ist die Zugriffsstufe des Kontos, nicht der Code. Metaculus vergibt
den Zugriff auf Community-Prediction-Aggregate gestuft; noetig ist der
kostenlose "Bot Benchmarking Access Tier", zu beantragen ueber das
Data-Needs-Formular auf https://www.metaculus.com/api/. Ein zweiter, davon
unabhaengiger Mechanismus ist cp_reveal_time: einzelne Fragen halten den
Median bis zu einem Stichtag zurueck.

Solange der Median fehlt, liefert diese Quelle bewusst nichts: eine Frage
ohne Vergleichszahl waere fuer dieses Projekt wertlos, weil es nichts
auszuwerten gibt und die Karte auf der Seite leer bliebe.

Sobald die Zugriffsstufe steht:

    python source_metaculus.py --probe

Dann steht in latest ein echter Wert, MEDIAN_PFADE kann auf den tatsaechlich
belegten Schluessel reduziert werden (centers oder means - welcher es ist,
laesst sich an einem leeren Objekt nicht entscheiden), und die Slugs in
METACULUS_KATEGORIEN lassen sich vollstaendig erfassen.
"""

import json
import os
import sys

import requests

# --- Konstanten ------------------------------------------------------------

QUELLE = "metaculus"

BASE_URL = "https://www.metaculus.com"
ENDPOINT = "/api/posts/"
ENV_DATEI = ".env"
TOKEN_NAME = "METACULUS_API_TOKEN"

HEADERS_BASIS = {"User-Agent": "africa-ai-forecasting/1.0"}
TIMEOUT = 30
PRO_SEITE = 100            # Seitengroesse fuer die Paginierung
MAX_SEITEN = 10            # Sicherheitsgrenze, damit die Schleife endet

# Filter fuer die Abfrage. Wir wollen nur offene, binaere Fragen: alles andere
# (numerische Fragen, Datumsfragen, geschlossene Fragen) passt nicht zu einer
# Ja/Nein-Prognose mit einer Wahrscheinlichkeit zwischen 0 und 1.
FILTER = {
    "statuses": "open",
    "forecast_type": "binary",
}

# Kandidatenpfade fuer den Community-Median, in dieser Reihenfolge probiert.
# Eine Zahl im Pfad ist ein Listenindex, ein Text ein Dict-Schluessel.
# NOCH NICHT verifiziert - siehe Modul-Docstring.
MEDIAN_PFADE = [
    ("question", "aggregations", "recency_weighted", "latest", "centers", 0),
    ("question", "aggregations", "recency_weighted", "latest", "means", 0),
    ("question", "aggregations", "unweighted", "latest", "centers", 0),
    ("question", "community_prediction", "full", "q2"),
    ("community_prediction", "full", "q2"),
]

# Kandidatenpfade fuer die Zahl der Prognostiker. Sie dient als Ersatz fuer das
# Handelsvolumen: fetch_markets.py sortiert die Auswahl danach, und je mehr
# Leute mitprognostiziert haben, desto belastbarer ist der Median.
# Verifiziert: nr_forecasters steht auf oberster Ebene, nicht in question.
# Die uebrigen Pfade bleiben als Rueckfallebene stehen, falls sich das Schema
# aendert.
FORECASTER_PFADE = [
    ("nr_forecasters",),
    ("forecasts_count",),
    ("question", "nr_forecasters"),
]

# Verifiziert: question.resolution_criteria. description steht als letzte
# Rueckfallebene dahinter, weil sie den Kontext enthaelt, aber nicht die Regeln.
KRITERIEN_PFADE = [
    ("question", "resolution_criteria"),
    ("resolution_criteria",),
    ("question", "description"),
]

# Zuordnung der Metaculus-Kategorie (projects.category[0].slug) auf unsere
# Kategorien. Nur "economy-business" ist an echten Daten verifiziert; die
# uebrigen Slugs sind unbekannt, solange die Zugriffsstufe fehlt und wir keine
# breite Stichprobe sehen. Ein unbekannter Slug liefert bewusst KEINEN
# Hinweis - dann greifen die Keyword-Regeln in fetch_markets.py, statt dass
# eine geratene Zuordnung eine falsche Kategorie setzt.
METACULUS_KATEGORIEN = {
    "economy-business": "economy",
}


# --- Token laden -----------------------------------------------------------

def lade_token():
    """Liest METACULUS_API_TOKEN aus der .env-Datei, sonst aus der Umgebung.

    Gleiche Machart wie lade_env_key() in forecast.py. Die Wiederholung ist
    bewusst in Kauf genommen, damit jede Quelle fuer sich lauffaehig bleibt;
    wenn forecast.py das naechste Mal angefasst wird, gehoert das in einen
    gemeinsamen kleinen Helfer.

    Gibt None zurueck, wenn kein Token da ist. Das ist kein Fehler: die Quelle
    meldet sich dann ab und die Pipeline laeuft ohne sie weiter.
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


def baue_headers(token):
    """Baut die Request-Header inklusive Authentifizierung.

    Metaculus erwartet das Token mit dem Praefix "Token" und einem Leerzeichen
    davor, nicht "Bearer".
    """
    headers = dict(HEADERS_BASIS)
    headers["Authorization"] = f"Token {token}"
    return headers


# --- Antwort auslesen ------------------------------------------------------

def lies_pfad(objekt, pfad):
    """Folgt einem Pfad durch verschachtelte Dicts und Listen.

    Gibt None zurueck, sobald ein Schritt nicht passt - fehlender Schluessel,
    zu kurze Liste, falscher Typ. So koennen wir mehrere Kandidatenpfade
    gefahrlos durchprobieren, ohne jedes Mal auf Fehler zu pruefen.
    """
    if isinstance(pfad, str):
        pfad = (pfad,)

    aktuell = objekt
    for schritt in pfad:
        if isinstance(schritt, int):
            if not isinstance(aktuell, list) or len(aktuell) <= schritt:
                return None
            aktuell = aktuell[schritt]
        else:
            if not isinstance(aktuell, dict) or schritt not in aktuell:
                return None
            aktuell = aktuell[schritt]

    return aktuell


def ersten_treffer(post, pfade):
    """Probiert mehrere Pfade und gibt den ersten Wert zurueck, der existiert."""
    for pfad in pfade:
        wert = lies_pfad(post, pfad)
        if wert is not None:
            return wert
    return None


def lies_community_median(post):
    """Liest den Community-Median als Zahl zwischen 0 und 1, sonst None.

    Metaculus gibt Wahrscheinlichkeiten binaerer Fragen als Anteil an (0 bis 1).
    Sollte ein Pfad doch Prozent liefern, faengt die Plausibilitaetspruefung
    unten das ab: alles ausserhalb von 0 bis 1 wird verworfen, statt einen
    Wert wie 62 als "6200 Prozent" durchzureichen.
    """
    wert = ersten_treffer(post, MEDIAN_PFADE)
    if wert is None:
        return None

    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return None

    if not 0.0 <= zahl <= 1.0:
        return None

    return zahl


def melde_fehlenden_median(post):
    """Erklaert, WARUM kein Median gelesen werden konnte.

    Zwei sehr verschiedene Ursachen sehen im Ergebnis gleich aus, brauchen
    aber gegensaetzliche Reaktionen:

    1. Der Pfad existiert, steht aber auf null. Dann fehlt die Zugriffsstufe
       (oder cp_reveal_time liegt in der Zukunft) - am Code ist nichts zu tun.
    2. Der Pfad existiert gar nicht. Dann hat sich das Schema geaendert und
       MEDIAN_PFADE muss angepasst werden.

    Ein stilles Ueberspringen saehe in beiden Faellen aus wie "Metaculus hat
    gerade nichts", darum melden wir es ausdruecklich.
    """
    frage = post.get("question")
    aggregationen = frage.get("aggregations") if isinstance(frage, dict) else None

    if isinstance(aggregationen, dict) and "recency_weighted" in aggregationen:
        # Fall 1: Struktur stimmt, Werte fehlen.
        reveal = frage.get("cp_reveal_time")
        print(f"  {QUELLE}: Struktur stimmt, aber der Community-Median ist leer "
              f"(latest = null).", file=sys.stderr)
        print(f"    Das ist eine Frage der Zugriffsstufe, nicht des Codes. "
              f"Bot-Benchmarking-Tier beantragen ueber das Data-Needs-Formular "
              f"auf {BASE_URL}/api/.", file=sys.stderr)
        print(f"    cp_reveal_time dieser Frage: {reveal}", file=sys.stderr)
        return

    # Fall 2: Struktur unbekannt.
    print(f"  {QUELLE}: kein bekannter Pfad zum Community-Median - das Schema "
          f"hat sich vermutlich geaendert.", file=sys.stderr)
    print(f"    Schluessel im Post:     {sorted(post.keys())}", file=sys.stderr)
    if isinstance(frage, dict):
        print(f"    Schluessel in question: {sorted(frage.keys())}", file=sys.stderr)
    print("    Vollstaendige Struktur: python source_metaculus.py --probe",
          file=sys.stderr)


# --- Normalisieren ---------------------------------------------------------

def hole_kategorie_hinweis(post):
    """Uebersetzt die Metaculus-Kategorie in unsere, sonst None.

    Metaculus fuehrt eigene Kategorien unter projects.category. Wo sich eine
    davon sicher zuordnen laesst, ist das verlaesslicher als ein Keyword im
    Fragetext - dasselbe Prinzip wie electionType bei Polymarket.

    Unbekannte Slugs geben None zurueck, nicht "other": None heisst "kein
    Hinweis, bitte Keywords anwenden", other waere eine Behauptung.
    """
    kategorien = (post.get("projects") or {}).get("category") or []
    for kategorie in kategorien:
        treffer = METACULUS_KATEGORIEN.get(kategorie.get("slug"))
        if treffer:
            return treffer
    return None


def normalisiere(post):
    """Macht aus einem Metaculus-Post einen Eintrag im gemeinsamen Format.

    Gibt None zurueck, wenn kein Community-Median sichtbar ist. Solche Fragen
    sind fuer dieses Projekt nutzlos: ohne Vergleichszahl gibt es nichts
    auszuwerten und die Karte auf der Seite waere leer.

    Jede Frage bildet ihr eigenes Event. Metaculus buendelt Fragen nicht wie
    Polymarket in Kandidatenvarianten, darum gibt es hier nichts zu entdoppeln.
    """
    median = lies_community_median(post)
    if median is None:
        return None

    forecaster = ersten_treffer(post, FORECASTER_PFADE)
    kriterien = ersten_treffer(post, KRITERIEN_PFADE) or ""

    return {
        "id": f"{QUELLE}-{post['id']}",
        "source": QUELLE,
        "question": post.get("title", ""),
        "market_p": median,
        # Kein Geldeinsatz, sondern der Median freiwilliger Prognosen. Die
        # Unterscheidung zieht sich bis auf die Karte durch.
        "benchmark_type": "community_forecast",
        "description": str(kriterien),
        "volume": float(forecaster) if forecaster else 0.0,
        "event_id": f"{QUELLE}-{post['id']}",
        "event_title": post.get("title", ""),
        "category_hint": hole_kategorie_hinweis(post),
    }


# --- Daten laden -----------------------------------------------------------

def lade_seite(headers, offset):
    """Holt eine Seite und gibt (posts, gibt_es_weitere) zurueck."""
    params = dict(FILTER, limit=PRO_SEITE, offset=offset)
    antwort = requests.get(
        BASE_URL + ENDPOINT, params=params, headers=headers, timeout=TIMEOUT
    )
    antwort.raise_for_status()

    daten = antwort.json()
    posts = daten.get("results", [])
    # Solange eine volle Seite kam, kann noch mehr folgen.
    return posts, len(posts) == PRO_SEITE


def lade_fragen():
    """Laedt offene binaere Metaculus-Fragen im gemeinsamen Format.

    Ohne Token meldet sich die Quelle ab und gibt eine leere Liste zurueck -
    das ist der Normalfall, solange kein Token hinterlegt ist, und kein Grund,
    die ganze Pipeline abzubrechen. Dasselbe gilt fuer HTTP-Fehler: die
    Warnung geht nach stderr, fetch_markets.py macht mit den uebrigen Quellen
    weiter.
    """
    token = lade_token()
    if not token:
        print(f"  {QUELLE}: kein {TOKEN_NAME} gesetzt, 0 Fragen.")
        return []

    headers = baue_headers(token)
    fragen = []
    ohne_median = 0
    erster_post = None   # fuer die Schema-Meldung, falls gar nichts passt

    try:
        for seite in range(MAX_SEITEN):
            posts, weitere = lade_seite(headers, seite * PRO_SEITE)

            for post in posts:
                if erster_post is None:
                    erster_post = post

                eintrag = normalisiere(post)
                if eintrag is None:
                    ohne_median += 1
                    continue
                fragen.append(eintrag)

            # Abbruch nach der ersten Seite, wenn dort KEINE einzige Frage
            # einen Median hatte. Fehlt der Zugriff, liefern die restlichen
            # neun Seiten garantiert dasselbe - das waeren neun nutzlose
            # Anfragen pro Lauf, und Metaculus antwortet auf zu viele
            # Anfragen mit HTTP 429.
            if seite == 0 and not fragen and posts:
                break

            if not weitere:
                break

    except requests.exceptions.RequestException as fehler:
        print(f"  {QUELLE}: Abfrage fehlgeschlagen ({type(fehler).__name__}), "
              f"Quelle wird uebersprungen.", file=sys.stderr)
        return []

    # Erst am Ende urteilen: einzelne Fragen ohne Median sind normal (Stichtag
    # oder Kontingent), aber KEINE einzige verwertbare Frage deutet auf ein
    # groesseres Problem hin - fehlender Zugriff oder geaendertes Schema.
    if not fragen and erster_post is not None:
        melde_fehlenden_median(erster_post)

    print(f"  {QUELLE}: {len(fragen)} Fragen mit sichtbarem Community-Median "
          f"({ohne_median} ohne, verworfen).")
    return fragen


# --- Probe-Modus -----------------------------------------------------------

def probe():
    """Gibt einen einzelnen Post als formatiertes JSON aus.

    Damit klopfen wir die Feldzuordnung fest, sobald ein Token vorliegt:
    einmal ansehen, MEDIAN_PFADE auf den tatsaechlichen Pfad reduzieren, den
    Modul-Docstring aktualisieren.
    """
    token = lade_token()
    if not token:
        print(f"Fehler: {TOKEN_NAME} ist nicht gesetzt. Trage das Token in die "
              f".env-Datei ein ({TOKEN_NAME}=...) oder setze die "
              f"Umgebungsvariable.", file=sys.stderr)
        sys.exit(1)

    params = dict(FILTER, limit=1, offset=0)
    antwort = requests.get(
        BASE_URL + ENDPOINT, params=params, headers=baue_headers(token),
        timeout=TIMEOUT,
    )
    print(f"HTTP {antwort.status_code}  {antwort.url}", file=sys.stderr)
    antwort.raise_for_status()

    daten = antwort.json()
    print(f"Top-Level-Schluessel: {sorted(daten.keys())}", file=sys.stderr)

    posts = daten.get("results", [])
    if not posts:
        print("Keine Posts in der Antwort.", file=sys.stderr)
        return

    print(json.dumps(posts[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # Die Windows-Konsole arbeitet standardmaessig mit cp1252. Metaculus-
    # Fragetexte enthalten gelegentlich Emojis, und die lassen jede Ausgabe
    # mit UnicodeEncodeError abstuerzen. errors="replace" ist bewusst
    # gewaehlt: ein Fragezeichen statt Emoji ist harmlos, ein Absturz nicht.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if "--probe" in sys.argv:
        probe()
    else:
        for eintrag in lade_fragen():
            print(f"  p={eintrag['market_p']}  {eintrag['question'][:70]}")
