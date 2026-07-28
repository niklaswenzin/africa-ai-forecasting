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
ANZAHL = 5                 # so viele Fragen wollen wir am Ende speichern
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
# Namibia ... vs Uganda"). Die APIs liefern keine verlaessliche Kategorie,
# darum diese Negativliste als einfacher, gut lesbarer Ersatz.
SPORT_KEYWORDS = [
    "cricket", "cup", "league", "fifa", "uefa", "nba", "nfl", "mlb",
    "t20", "odi", "tournament", "quadrangular", " vs ", "vs.", " fc ", "match",
]


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


def ist_moderat(frage):
    """True, wenn die Quote existiert und nicht extrem ist (zwischen den Grenzen)."""
    p = frage.get("market_p")
    return p is not None and MODERAT_MIN <= p <= MODERAT_MAX


# --- Auswahl ---------------------------------------------------------------

def naechste_passende(kandidaten, gesehene_laender):
    """Gibt die erste Frage zurueck, deren Land noch nicht vertreten ist.

    Die Kandidatenlisten sind bereits nach Volumen sortiert, die erste
    passende ist also zugleich die aktivste.
    """
    for frage in kandidaten:
        if land_von_frage(frage) not in gesehene_laender:
            return frage
    return None


def waehle_reihum(nach_quelle, gewaehlt, gesehene_laender):
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

            frage = naechste_passende(kandidaten, gesehene_laender)
            if frage is None:
                continue  # diese Quelle hat gerade nichts Passendes

            kandidaten.remove(frage)
            gesehene_laender.add(land_von_frage(frage))
            gewaehlt.append(frage)
            etwas_genommen = True

        # Eine komplette Runde ohne Treffer heisst: keine Quelle kann mehr.
        if not etwas_genommen:
            break


def waehle_fragen(nach_quelle):
    """Waehlt bis zu ANZAHL Fragen: max. eine pro Land, kein Sport, reihum.

    Bevorzugt Quoten zwischen MODERAT_MIN und MODERAT_MAX (erster Durchlauf).
    Nur wenn so nicht genug zusammenkommen, sind Extremwerte erlaubt (zweiter
    Durchlauf). Innerhalb jeder Quelle entscheidet das Volumen.
    """
    # Pro Quelle: nur Afrika-Fragen, nach Volumen sortiert, dann in moderate
    # und extreme Quoten aufgeteilt.
    moderate = {}
    extreme = {}
    for name, fragen in nach_quelle.items():
        afrika = [f for f in fragen if hat_afrika_bezug(f)]
        afrika.sort(key=lambda f: f.get("volume", 0.0), reverse=True)
        moderate[name] = [f for f in afrika if ist_moderat(f)]
        extreme[name] = [f for f in afrika if not ist_moderat(f)]
        print(f"  {name}: {len(afrika)} Fragen mit Afrika-Bezug "
              f"({len(moderate[name])} mit moderater Quote).")

    gewaehlt = []
    gesehene_laender = set()
    waehle_reihum(moderate, gewaehlt, gesehene_laender)  # 1. bevorzugt
    waehle_reihum(extreme, gewaehlt, gesehene_laender)   # 2. Notnagel
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
        "description": frage.get("description", ""),
    }


# --- Hauptablauf -----------------------------------------------------------

def main():
    print(f"Quellen abfragen ({len(QUELLEN)}):")
    nach_quelle = lade_alle_quellen()

    print("Auswahl:")
    gewaehlt = waehle_fragen(nach_quelle)
    print(f"{len(gewaehlt)} Fragen gewaehlt (max. eine pro Land, kein Sport).")

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

    # Weniger als ANZAHL? Dann NICHT mit anderen Themen auffuellen, sondern die
    # Luecke klar melden und nur die vorhandenen Fragen speichern.
    if len(eintraege) < ANZAHL:
        print(
            f"Warnung: nur {len(eintraege)} statt {ANZAHL} Afrika-Fragen gefunden. "
            f"Es wird NICHT mit anderen Themen aufgefuellt.",
            file=sys.stderr,
        )

    # ensure_ascii=False, damit Umlaute/Sonderzeichen lesbar bleiben.
    with open(MARKETS_DATEI, "w", encoding="utf-8") as datei:
        json.dump(eintraege, datei, ensure_ascii=False, indent=2)

    print(f"{len(eintraege)} Fragen in {MARKETS_DATEI} gespeichert.")
    for e in eintraege:
        print(f"  [{e['source']}] p={e['market_p']}  {e['question']}")


if __name__ == "__main__":
    main()
