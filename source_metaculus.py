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

Ursache ist die Zugriffsstufe des Kontos, nicht der Code. Das Konto meldet
sie selbst, am 31.07.2026 geprueft:

    GET /api/users/me/  ->  api_access_tier: "restricted"
                            hide_community_prediction: false

Das zweite Feld schliesst die naheliegende Verwechslung aus: es gibt eine
Profileinstellung, die den Median absichtlich verbirgt (damit man sich beim
eigenen Prognostizieren nicht daran anlehnt), und sie ist hier nicht aktiv.
Es bleibt die Stufe. Noetig ist der kostenlose "Bot Benchmarking Access
Tier", zu beantragen ueber das Data-Needs-Formular auf
https://www.metaculus.com/api/. Ein zweiter, davon unabhaengiger Mechanismus
ist cp_reveal_time: einzelne Fragen halten den Median bis zu einem Stichtag
zurueck.

Belegt ist es an der Antwort selbst: unter recency_weighted stehen alle vier
Schluessel (history, latest, movement, score_data), aber history ist leer und
latest null - auch bei einer Frage mit 199 Prognostikern, die auf der Website
offensichtlich einen Median hat. Eine beschnittene Antwort, kein fehlendes
Feld. Auch der Detail-Endpoint /api/posts/{id}/ liefert dasselbe.

Die Fragen kommen trotzdem mit: die Modelle koennen sie prognostizieren, die
Karte zeigt dann eben nur die Modelle. Ein geratener Ersatzwert kaeme nie in
Frage - er waere ein erfundener Benchmark.

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
import time

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
# Sicherheitsgrenze, damit die Schleife endet. Bewusst hoch: Fragen mit
# Afrika-Bezug sind selten (rund 9 auf die ersten 1000), und die API bietet
# keinen Themenfilter, den wir serverseitig setzen koennten. Wir muessen also
# breit laden und clientseitig filtern. 30 Seiten sind 30 Anfragen pro Lauf -
# vertretbar bei einem Lauf alle sechs Stunden.
MAX_SEITEN = 30

# Wiederholungen bei Rate Limit und Serverfehlern. 429 tritt real auf: die
# Action feuert bis zu MAX_SEITEN Anfragen kurz hintereinander, von einer
# geteilten Runner-IP.
WIEDERHOLBARE_CODES = (429, 500, 502, 503, 504)
MAX_VERSUCHE = 4
MAX_WARTEN = 30            # Sekunden, damit ein Lauf nicht ewig haengt

# Kleine Pause zwischen den Seiten. Verlangsamt einen Lauf um wenige Sekunden
# und senkt die Wahrscheinlichkeit, ueberhaupt in ein Limit zu laufen.
PAUSE_ZWISCHEN_SEITEN = 0.25

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


def lies_zugriffsstufe(headers):
    """Fragt das eigene Konto nach seiner API-Zugriffsstufe.

    Gibt (api_access_tier, hide_community_prediction) zurueck, bei jedem
    Fehler (None, None) - die Auskunft ist eine Diagnosehilfe und darf einen
    Lauf nie aufhalten.

    Der Sinn: ohne diese Abfrage bleibt "Median ist leer" eine Vermutung ueber
    die Ursache. Mit ihr steht im Protokoll, was das Konto selbst sagt, und
    zwar beide Male - denn "restricted" und die Profileinstellung
    hide_community_prediction fuehren zum selben leeren Feld, verlangen aber
    voellig verschiedene Reaktionen (Antrag stellen gegen einen Haken
    umlegen).
    """
    try:
        antwort = requests.get(
            BASE_URL + "/api/users/me/", headers=headers, timeout=TIMEOUT
        )
        if not antwort.ok:
            return None, None
        daten = antwort.json()
        return daten.get("api_access_tier"), daten.get("hide_community_prediction")
    except (requests.RequestException, ValueError):
        return None, None


def melde_fehlenden_median(post, headers=None):
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

        stufe, verborgen = lies_zugriffsstufe(headers) if headers else (None, None)
        if stufe is None:
            print(f"    Das ist eine Frage der Zugriffsstufe, nicht des Codes. "
                  f"Bot-Benchmarking-Tier beantragen ueber das "
                  f"Data-Needs-Formular auf {BASE_URL}/api/.", file=sys.stderr)
        elif verborgen:
            # Selbstverschuldet und in einer Minute behoben - darum zuerst.
            print(f"    Ursache liegt im Profil: hide_community_prediction ist "
                  f"aktiv. Haken in den Metaculus-Einstellungen entfernen, "
                  f"dann erscheint der Median.", file=sys.stderr)
        elif stufe != "restricted":
            # Stufe erhoeht, Median trotzdem leer: dann greift etwas anderes,
            # und die alte Erklaerung waere ab hier falsch.
            print(f"    api_access_tier ist \"{stufe}\", also nicht mehr "
                  f"beschraenkt - der leere Median hat dann eine andere "
                  f"Ursache. Struktur pruefen mit --probe.", file=sys.stderr)
        else:
            print(f"    api_access_tier: \"{stufe}\". Der Zugriff auf "
                  f"Community-Aggregate haengt daran, nicht am Code. "
                  f"Bot-Benchmarking-Tier beantragen ueber das "
                  f"Data-Needs-Formular auf {BASE_URL}/api/.", file=sys.stderr)

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

    market_p darf None sein. Frueher haben wir solche Fragen verworfen, weil
    ohne Vergleichszahl nichts auszuwerten ist. Da der Community-Median fuer
    dieses Konto durchgehend gesperrt ist, waere die Quelle damit aber komplett
    stumm. Stattdessen nehmen wir die Frage auf: die Karte zeigt dann den
    Claude-Forecast und "Community forecast pending" statt einer Quote.

    Der Vergleich Modell gegen Benchmark faellt fuer diese Fragen weg - das
    ist eine bewusste Einschraenkung, keine Luecke, die spaeter jemand fuer
    einen Fehler haelt. Sobald die Zugriffsstufe steht, fuellt sich die Zahl
    von selbst.

    Jede Frage bildet ihr eigenes Event. Metaculus buendelt Fragen nicht wie
    Polymarket in Kandidatenvarianten, darum gibt es hier nichts zu entdoppeln.
    """
    median = lies_community_median(post)
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
        # Zeitpunkt der geplanten Aufloesung. Fuer Fragen ohne Vergleichszahl
        # ist das die Sortiergroesse: was zuerst aufgeloest wird, ist zuerst
        # ueberpruefbar und damit am interessantesten.
        "resolve_time": post.get("scheduled_resolve_time") or "",
    }


# --- Daten laden -----------------------------------------------------------

def lade_seite(headers, offset):
    """Holt eine Seite und gibt (posts, gibt_es_weitere) zurueck.

    Wiederholt bei Rate Limit (429) und Serverfehlern mit wachsender Wartezeit.
    Das ist kein Luxus: wir machen bis zu MAX_SEITEN Anfragen kurz
    hintereinander, und in der GitHub Action kommen sie von einer geteilten
    Runner-IP, die andere Nutzer schon belastet haben koennen. Ohne Wiederholung
    faellt die ganze Quelle bei einem einzigen 429 aus - und die Fragen
    verschwinden von der Seite.

    Respektiert den Retry-After-Header, wenn die API einen mitschickt.
    """
    params = dict(FILTER, limit=PRO_SEITE, offset=offset)

    for versuch in range(1, MAX_VERSUCHE + 1):
        antwort = requests.get(
            BASE_URL + ENDPOINT, params=params, headers=headers, timeout=TIMEOUT
        )

        if antwort.status_code not in WIEDERHOLBARE_CODES:
            break

        if versuch == MAX_VERSUCHE:
            print(f"  {QUELLE}: HTTP {antwort.status_code} auch nach "
                  f"{MAX_VERSUCHE} Versuchen.", file=sys.stderr)
            break

        # Retry-After kann Sekunden enthalten; sonst warten wir zunehmend
        # laenger (2, 4, 8 ...), damit wir ein Limit nicht weiter befeuern.
        try:
            warten = float(antwort.headers.get("Retry-After", ""))
        except ValueError:
            warten = 2 ** versuch

        print(f"  {QUELLE}: HTTP {antwort.status_code}, warte {warten:.0f}s "
              f"(Versuch {versuch}/{MAX_VERSUCHE}) ...", file=sys.stderr)
        time.sleep(min(warten, MAX_WARTEN))

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
                    continue
                if eintrag["market_p"] is None:
                    ohne_median += 1
                fragen.append(eintrag)

            if not weitere:
                break

            time.sleep(PAUSE_ZWISCHEN_SEITEN)

    except requests.exceptions.RequestException as fehler:
        # Deutlich markiert, damit die Ursache im Action-Protokoll auf einen
        # Blick zu finden ist. Die Meldung der Auswahlphase ("0 Fragen mit
        # Afrika-Bezug") sagt nur, DASS nichts ankam, nicht warum.
        print(f"  {QUELLE}: AUSFALL - Abfrage fehlgeschlagen "
              f"({type(fehler).__name__}: {fehler}). Quelle liefert diesmal "
              f"nichts.", file=sys.stderr)
        return []

    # Fragen ohne Median werden jetzt mitgenommen, nicht mehr verworfen. Fehlt
    # der Median AUSNAHMSLOS, ist das trotzdem meldenswert: entweder fehlt die
    # Zugriffsstufe oder das Schema hat sich geaendert. Der Unterschied steht
    # in melde_fehlenden_median.
    mit_median = len(fragen) - ohne_median
    if mit_median == 0 and erster_post is not None:
        melde_fehlenden_median(erster_post, headers)

    print(f"  {QUELLE}: {len(fragen)} Fragen geladen "
          f"({mit_median} mit Community-Median, {ohne_median} ohne).")
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
