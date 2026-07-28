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

Was NOCH NICHT verifiziert ist
------------------------------
Das Antwortschema. Es liess sich ohne Token nicht einsehen, und die frei
verfuegbare OpenAPI-Datei beschreibt die alte /api2/-API, die es so nicht mehr
gibt. Wo genau der Community-Median steht, ist damit offen.

Statt einen Feldnamen zu raten, probiert lies_community_median() mehrere
bekannte Kandidatenpfade durch. Greift keiner, meldet die Funktion die
tatsaechlich vorhandenen Schluessel, statt still einen falschen Wert zu
liefern. Sobald ein Token vorliegt:

    python source_metaculus.py --probe

Das gibt einen vollstaendigen Post als JSON aus. Danach wird MEDIAN_PFADE auf
den tatsaechlichen Pfad reduziert und dieser Abschnitt hier aktualisiert.

Kontingentierung beachten
-------------------------
Der Community-Median ist bei Metaculus zugriffsbeschraenkt: normale Konten
sehen ihn nur bei einer begrenzten Zahl von Fragen, ein kostenloser
Bot-Benchmarking-Tier erweitert das Kontingent. Fragen ohne sichtbaren Median
sind fuer dieses Projekt wertlos, weil es dann nichts zu vergleichen gibt -
sie werden hier verworfen.
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
FORECASTER_PFADE = [
    ("question", "nr_forecasters"),
    ("nr_forecasters",),
    ("question", "forecasters_count"),
    ("forecasters_count",),
]

# Kandidatenpfade fuer die Aufloesungskriterien.
KRITERIEN_PFADE = [
    ("question", "resolution_criteria"),
    ("resolution_criteria",),
    ("question", "fine_print"),
    ("question", "description"),
]


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


def melde_unbekanntes_schema(post):
    """Gibt die vorhandenen Schluessel aus, wenn kein Median-Pfad gepasst hat.

    Absichtlich laut: ein stilles Ueberspringen saehe aus wie "Metaculus hat
    gerade nichts", waere aber in Wahrheit eine veraltete Feldzuordnung.
    """
    print(f"  {QUELLE}: kein bekannter Pfad zum Community-Median.",
          file=sys.stderr)
    print(f"    Schluessel im Post:     {sorted(post.keys())}", file=sys.stderr)
    frage = post.get("question")
    if isinstance(frage, dict):
        print(f"    Schluessel in question: {sorted(frage.keys())}", file=sys.stderr)
    print("    Vollstaendige Struktur: python source_metaculus.py --probe",
          file=sys.stderr)


# --- Normalisieren ---------------------------------------------------------

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
        # Metaculus kennt kein Gegenstueck zu Polymarkets electionType, die
        # Kategorie kommt darum ueber die Keyword-Regeln in fetch_markets.py.
        "category_hint": None,
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

            if not weitere:
                break

    except requests.exceptions.RequestException as fehler:
        print(f"  {QUELLE}: Abfrage fehlgeschlagen ({type(fehler).__name__}), "
              f"Quelle wird uebersprungen.", file=sys.stderr)
        return []

    # Erst am Ende urteilen: einzelne Fragen ohne Median sind normal (das
    # Kontingent), aber KEINE einzige verwertbare Frage bei vorhandenen Posts
    # deutet auf eine veraltete Feldzuordnung hin.
    if not fragen and erster_post is not None:
        melde_unbekanntes_schema(erster_post)

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
    if "--probe" in sys.argv:
        probe()
    else:
        for eintrag in lade_fragen():
            print(f"  p={eintrag['market_p']}  {eintrag['question'][:70]}")
