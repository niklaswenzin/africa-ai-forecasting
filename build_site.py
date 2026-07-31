"""build_site.py

Liest markets.json und forecasts.json und schreibt daraus eine statische
Seite docs/index.html. Kein Framework, keine zusaetzlichen Bibliotheken:
nur die Standardbibliothek, das Filtern uebernimmt etwas Vanilla-JS.

Ausgangspunkt sind die Fragen aus markets.json, nicht die Prognosen. Jede
ausgewaehlte Frage bekommt einen Register-Eintrag mit der Vergleichszahl und
beiden Modellen. Jede dieser Zahlen kann fehlen, und jeder Fall hat eine
eigene, ruhige Darstellung - nie eine Zahl, die es nicht gibt, nie eine
leere Stelle.

Darstellung: ein durchnummeriertes Register, keine Kacheln. Trennung ueber
Haarlinien und Weissraum statt ueber Rahmen, Schatten und gefuellte Pillen.
Alles Zaehlbare - Zahlen, Kuerzel, Datumsangaben - steht in einer
Festbreitenschrift, alles Gelesene in einer Grotesk; das trennt Messwert von
Text, ohne dass es dafuer Farbe braucht.

Farbe bedeutet WER, nicht WAS: Benchmark, Claude und ChatGPT haben je eine
feste Farbe, die in der Zahl und im Punkt auf der Skala wiederkehrt. Die
Kategorie bleibt darum unbunt - zwei konkurrierende Farbsysteme auf einem
Eintrag machen beide unlesbar.

Das Kernstueck jedes Eintrags ist die gemeinsame Skala von 0 bis 100 Prozent,
auf der alle Schaetzungen als Punkte liegen. Drei getrennte grosse Zahlen
zwingen zum Kopfrechnen; auf einer Achse sieht man Uneinigkeit sofort. Sie
erscheint erst ab zwei Punkten - eine Achse mit einem einzelnen Punkt zeigt
keinen Vergleich, sondern wiederholt nur die Zahl darueber.

Die Reihenfolge ist das Aufloesungsdatum, naechste zuerst. Bewusst nicht die
Abweichung vom Benchmark: das las sich wie eine Rangliste der groessten
Marktirrtuemer, und diese Aussage ist durch nichts gedeckt, solange keine
Frage aufgeloest ist.

Die Seite selbst ist auf Englisch, weil sie oeffentlich ist. Kommentare und
Funktionsnamen bleiben deutsch wie im Rest des Projekts.
"""

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import forecast
import forecaster_openai

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
AUSGABE_ORDNER = Path("docs")
AUSGABE_DATEI = AUSGABE_ORDNER / "index.html"

REPO_URL = "https://github.com/niklaswenzin/africa-ai-forecasting"

QUELLEN_NAMEN = {
    "polymarket": "Polymarket",
    "metaculus": "Metaculus",
}

# Beschriftung der Vergleichszahl. Ein Polymarket-Preis entsteht durch echten
# Geldeinsatz, der Metaculus-Wert ist der Median freiwilliger Community-
# Prognosen. Beides "Market" zu nennen waere irrefuehrend.
BENCHMARK_LABEL = {
    "market_price": "Market",
    "community_forecast": "Community",
}

# Text, wenn die Vergleichszahl fehlt. Haengt am benchmark_type, weil die
# Ursache unterschiedlich ist: bei Metaculus ist der Median fuer unsere
# Zugriffsstufe gesperrt, bei einem Geldmarkt fehlt schlicht ein Preis.
BENCHMARK_FEHLT = {
    "market_price": "no price",
    "community_forecast": "median locked",
}

# Prognostiker in fester Reihenfolge: Schluessel in forecasts.json,
# Anzeigename auf der Karte, und die tatsaechlich verwendete Modell-ID.
#
# Die Modell-IDs werden aus den Prognostiker-Modulen gelesen, nicht hier
# abgeschrieben. Die Fusszeile nannte sonst weiter claude-sonnet-4-6, obwohl
# laengst ein anderes Modell lief - genau das ist auf der Live-Seite passiert.
# So kann der Text nicht mehr veralten.
PROGNOSTIKER = [
    ("claude", "Claude", forecast.MODEL),
    ("openai", "ChatGPT", forecaster_openai.MODELL),
]

KATEGORIE_NAMEN = [
    ("elections", "Elections"),
    ("security", "Security"),
    ("diplomacy", "Diplomacy"),
    ("economy", "Economy"),
    ("other", "Other"),
]

# Bewusst KEINE Flaggen-Emoji am Laender-Tag: Windows liefert dafuer keine
# Glyphe und zeigt stattdessen das nackte Buchstabenpaar des Laendercodes
# ("ZA South Africa"). Das sah auf der Haelfte der Karten nach einem Fehler
# aus, waehrend Somaliland - ohne ISO-Code und damit ohne Emoji - als
# einziges eine Weltkugel trug. Der Landesname allein ist auf jedem System
# gleich lesbar.


# --- Vorlagen --------------------------------------------------------------
#
# Platzhalter in doppelten spitzen Klammern, eingesetzt mit str.replace.
# Bewusst nicht .format() oder f-Strings: CSS und JavaScript enthalten
# geschweifte Klammern, die beide Verfahren als Platzhalter missverstehen.

SEITEN_VORLAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Forecasting: African Economics and Politics</title>
<meta name="description" content="Two AI models forecast open questions on African
economics and politics, shown next to prediction-market prices.">
<style>
/* Register statt Kartenraster. Keine Schlagschatten, keine abgerundeten
   Ecken, keine gefuellten Pillen: Trennung passiert ueber Haarlinien und
   Weissraum. Alles Zaehlbare - Zahlen, Kuerzel, Datumsangaben - steht in
   einer Festbreitenschrift, alles Gelesene in einer Grotesk. Das trennt
   Messwert von Text, ohne dass es dafuer Farbe oder Rahmen braucht. */
:root {
  --papier: #fcfcfa;
  --ton: #f4f4f0;
  --tinte: #16181a;
  --tinte-weich: #454a4e;
  --matt: #767b80;
  --linie: #dedbd4;
  --linie-fein: #ebe9e3;
  --link: #1a4fb8;

  /* Farbe bedeutet WER. Diese drei sind ueber die ganze Seite reserviert. */
  --bench: #16181a;
  --claude: #b4552e;
  --gpt: #0c7f62;
  --modell-standard: #6f7378;

  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
          "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --papier: #0c0d0e;
    --ton: #141618;
    --tinte: #e9eaeb;
    --tinte-weich: #aeb3b8;
    --matt: #838890;
    --linie: #272a2e;
    --linie-fein: #1c1f22;
    --link: #7aa7ff;

    --bench: #e9eaeb;
    --claude: #dd8a5e;
    --gpt: #35c4a0;
    --modell-standard: #939aa1;
  }
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 0 1.3rem 5rem;
  background: var(--papier);
  color: var(--tinte);
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1060px; margin: 0 auto; }

/* --- Kopf --- */
header.top { padding: 4rem 0 2.25rem; }
.kicker {
  font-family: var(--mono);
  font-size: .69rem;
  text-transform: uppercase;
  letter-spacing: .13em;
  color: var(--matt);
  margin: 0 0 1.5rem;
  padding-bottom: .75rem;
  border-bottom: 1px solid var(--tinte);
}
/* Ueberschrift ohne max-width: sie soll die volle Spaltenbreite einnehmen.
   Vorher brach sie bei 15ch auf drei Zeilen um und liess rechts eine grosse
   leere Flaeche stehen. Die Schriftgroesse waechst mit dem Fenster mit, damit
   die Zeile bis zum Rand traegt statt bei halber Breite zu enden. */
h1 {
  font-size: clamp(2rem, 6.4vw, 4.1rem);
  line-height: 1.02;
  letter-spacing: -.04em;
  font-weight: 620;
  margin: 0 0 1.3rem;
}
.lede {
  color: var(--tinte-weich);
  margin: 0;
  /* Ohne Begrenzung, damit der Absatz wie die Ueberschrift die volle
     Spaltenbreite nutzt. Die Zeile wird dadurch lang; die etwas groessere
     Schrift und der weitere Zeilenabstand halten sie lesbar. */
  font-size: 1.12rem;
  line-height: 1.65;
}

/* Legende: erklaert das Farbsystem genau einmal */
.legende {
  display: flex;
  flex-wrap: wrap;
  gap: 1.4rem;
  margin: 2rem 0 0;
  font-family: var(--mono);
  font-size: .715rem;
  text-transform: uppercase;
  letter-spacing: .07em;
  color: var(--tinte-weich);
}
.legende span { display: inline-flex; align-items: center; gap: .45rem; }
.strich { width: .85rem; height: 2px; background: currentColor; flex: none; }

/* --- Steuerleiste --- */
.leiste {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: .7rem;
  margin-top: 2.75rem;
  padding-bottom: .6rem;
  border-bottom: 1px solid var(--tinte);
}
.tabs { display: flex; flex-wrap: wrap; gap: 1.25rem; }
.tab {
  font-family: var(--mono);
  font-size: .715rem;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--matt);
  background: none;
  border: 0;
  padding: 0 0 .12rem;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color .12s, border-color .12s;
}
.tab:hover { color: var(--tinte); }
.tab.active { color: var(--tinte); border-bottom-color: var(--tinte); }
.tab .zahl { color: var(--matt); margin-left: .35rem; }
.sortnote {
  font-family: var(--mono);
  font-size: .69rem;
  text-transform: uppercase;
  letter-spacing: .07em;
  color: var(--matt);
}

/* --- Register --- */
.register { list-style: none; margin: 0; padding: 0; }
.eintrag {
  display: grid;
  grid-template-columns: 3.1rem 1fr;
  gap: 0 .5rem;
  padding: 1.7rem 0 1.9rem;
  border-bottom: 1px solid var(--linie-fein);
}
/* Der letzte Eintrag braucht keine Trennlinie: direkt darunter beginnt die
   Fusszeile mit ihrer eigenen, kraeftigeren Linie, und zwei Striche kurz
   untereinander sehen nach einem Fehler aus. */
.eintrag:last-child { border-bottom: 0; }
@media (max-width: 620px) {
  .eintrag { grid-template-columns: 1fr; }
  .nummer { margin-bottom: .5rem; }
}
.nummer {
  font-family: var(--mono);
  font-size: .72rem;
  color: var(--matt);
  padding-top: .3rem;
  font-variant-numeric: tabular-nums;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: .55rem;
  font-family: var(--mono);
  font-size: .685rem;
  text-transform: uppercase;
  letter-spacing: .075em;
  color: var(--matt);
  margin-bottom: .55rem;
}
.meta .trenner { opacity: .45; }
.meta .kat { color: var(--tinte-weich); }
.meta .datum { margin-left: auto; white-space: nowrap; }

.frage {
  font-size: 1.17rem;
  font-weight: 500;
  line-height: 1.34;
  letter-spacing: -.014em;
  margin: 0 0 1.15rem;
  max-width: 44ch;
}

/* Zahlenreihe. Jede Spalte traegt ihre Modellfarbe ueber --farbe. */
.zahlen { display: flex; flex-wrap: wrap; gap: 2.2rem; margin-bottom: 1.35rem; }
.z { --farbe: var(--modell-standard); min-width: 4.4rem; }
.z-bench { --farbe: var(--bench); }
.z-claude { --farbe: var(--claude); }
.z-openai { --farbe: var(--gpt); }
.k {
  display: block;
  font-family: var(--mono);
  font-size: .655rem;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: var(--matt);
  margin-bottom: .3rem;
}
.v {
  display: block;
  font-family: var(--mono);
  font-size: 1.85rem;
  font-weight: 500;
  line-height: 1;
  letter-spacing: -.045em;
  font-variant-numeric: tabular-nums;
  color: var(--farbe);
}
.leer {
  display: block;
  font-family: var(--mono);
  font-size: .82rem;
  color: var(--matt);
  /* Auf die Grundlinie der Zahlen gesetzt, damit die Reihe nicht verspringt,
     wenn nur ein Teil belegt ist. */
  padding: .75rem 0 .28rem;
}

/* Gemeinsame Skala: Abstand gleich Uneinigkeit. */
.skala { position: relative; height: 1.05rem; }
.achse {
  position: absolute;
  top: .5rem;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--linie);
}
.tick { position: absolute; top: .24rem; width: 1px; height: .52rem; background: var(--linie); }
.mk {
  position: absolute;
  top: .16rem;
  width: .72rem;
  height: .72rem;
  border-radius: 50%;
  background: var(--farbe);
  /* Ring in der Papierfarbe: liegen zwei Punkte fast uebereinander, bleiben
     sie trotzdem als zwei erkennbar. */
  box-shadow: 0 0 0 2.5px var(--papier);
  transform: translateX(-50%);
}
.mk-bench { --farbe: var(--bench); z-index: 3; }
.mk-claude { --farbe: var(--claude); z-index: 2; }
.mk-openai { --farbe: var(--gpt); z-index: 1; }
.enden {
  display: flex;
  justify-content: space-between;
  margin-top: .95rem;
  font-family: var(--mono);
  font-size: .6rem;
  color: var(--matt);
  letter-spacing: .05em;
}

/* Widerspruch zwischen Zahl und Begruendung. */
.warnung {
  margin: .35rem 0 0;
  font-family: var(--mono);
  font-size: .655rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: #a8580a;
  cursor: help;
}
@media (prefers-color-scheme: dark) { .warnung { color: #e0a163; } }

/* Ohne max-width: die Trennlinie soll wie die Linie unter der Kopfzeile ueber
   die ganze Spalte laufen. Mit 68ch endete sie auf halber Strecke und sah aus,
   als waere die Seite dort zu Ende. */
footer {
  margin-top: 3rem;
  padding-top: 1.4rem;
  border-top: 1px solid var(--tinte);
  font-size: .84rem;
  color: var(--matt);
  line-height: 1.65;
}
footer a { color: var(--link); text-decoration: none; }
footer a:hover { text-decoration: underline; }
footer p { margin: 0 0 .55rem; }
footer code { font-family: var(--mono); font-size: .93em; }
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <p class="kicker">Prediction markets &middot; Large language models &middot; <<ANZAHL>> open questions</p>
  <h1>Can AI forecast African economics and politics?</h1>
  <p class="lede">Two language models estimate the probability of open questions
  on African economies and governments. Neither ever sees the market price it is
  placed next to, so each estimate is an independent claim rather than a
  restatement of the crowd.</p>

  <div class="legende">
    <span><i class="strich" style="background: var(--bench)"></i> <<LEGENDE_BENCH>></span>
<<LEGENDE_MODELLE>>
  </div>
</header>

<div class="leiste">
  <nav class="tabs"><<TABS>></nav>
  <span class="sortnote">Ordered by resolution date</span>
</div>

<ol class="register">
<<KARTEN>>
</ol>

<footer>
<p>Forecasts come from <<MODELL_LISTE>>. Both receive the same question, the same
resolution criteria and the same web-search tool, with prediction-market sites
blocked. The benchmark is never passed into the prompt.</p>
<p>Benchmarks from <<QUELLEN_LISTE>> &middot; last updated <<ZEITSTEMPEL>> &middot;
<a href="<<REPO_URL>>">source code and method</a></p>
</footer>

</div>

<script>
// Tab-Filter. Jeder Eintrag traegt seine Kategorie als data-category, jeder Tab
// den gewuenschten Filter als data-filter. Es wird nichts nachgeladen, wir
// blenden nur aus - ohne JavaScript bleiben darum alle Eintraege sichtbar.
document.querySelectorAll(".tab").forEach(function (tab) {
  tab.addEventListener("click", function () {
    var filter = tab.getAttribute("data-filter");

    document.querySelectorAll(".tab").forEach(function (anderer) {
      anderer.classList.remove("active");
    });
    tab.classList.add("active");

    document.querySelectorAll(".eintrag").forEach(function (eintrag) {
      var passt = (filter === "all") || (eintrag.getAttribute("data-category") === filter);
      eintrag.style.display = passt ? "" : "none";
    });
  });
});
</script>
</body>
</html>
"""

KARTEN_VORLAGE = """<li class="eintrag" data-category="<<KATEGORIE>>">
  <div class="nummer"><<NUMMER>></div>
  <div>
    <div class="meta">
      <span class="kat"><<KATEGORIE_NAME>></span>
      <span class="trenner">/</span>
      <span><<QUELLE>></span>
      <span class="trenner">/</span>
      <span><<LAND>></span>
<<VOLUMEN>>
      <span class="datum">Resolves <<DATUM>></span>
    </div>
    <h2 class="frage"><<FRAGE>></h2>
    <div class="zahlen">
<<BENCHMARK_BLOCK>>
<<AI_BLOCK>>
    </div>
<<SKALA>>
  </div>
</li>"""

BENCHMARK_VORLAGE = """      <div class="z z-bench">
        <span class="k"><<BENCHMARK_LABEL>></span>
        <span class="v"><<MARKT_P>></span>
      </div>"""

# Vergleichszahl fehlt: dieselbe Beschriftung, aber ein ruhiger Hinweis statt
# einer Zahl. Bewusst keine 0 - das waere eine Behauptung ueber einen Wert,
# den wir nicht haben.
BENCHMARK_FEHLT_VORLAGE = """      <div class="z z-bench">
        <span class="k"><<BENCHMARK_LABEL>></span>
        <span class="leer"><<HINWEIS>></span>
      </div>"""

# Auf dem Eintrag steht nur die Zahl. Weder Konfidenz und Suchanzahl (Angaben
# ueber den Weg, nicht ueber das Ergebnis) noch die Differenz zum Benchmark:
# die Skala darunter zeigt den Abstand bereits als Bild. Gespeichert bleibt
# alles in forecasts.json und in jeder Aufnahme.
AI_VORLAGE = """      <div class="z z-<<SCHLUESSEL>>">
        <span class="k"><<MODELL_NAME>></span>
        <span class="v"><<MODELL_P>></span>
<<WARNUNG>>
      </div>"""

OHNE_AI_VORLAGE = """      <div class="z z-<<SCHLUESSEL>>">
        <span class="k"><<MODELL_NAME>></span>
        <span class="leer">pending</span>
      </div>"""

WARNUNG_VORLAGE = """        <p class="warnung" title="<<GRUND>>">&#9888; contradicts its reasoning</p>"""

SKALA_VORLAGE = """    <div class="skala">
      <div class="achse"></div>
      <div class="tick" style="left: 25%"></div>
      <div class="tick" style="left: 50%"></div>
      <div class="tick" style="left: 75%"></div>
<<PUNKTE>>
    </div>
    <div class="enden"><span>0%</span><span>100%</span></div>"""

PUNKT_VORLAGE = """      <div class="mk mk-<<SCHLUESSEL>>" style="left: <<POSITION>>%" title="<<TITEL>>"></div>"""

LEGENDE_VORLAGE = """    <span><i class="strich" style="background: var(--<<FARBE>>)"></i> <<MODELL_NAME>></span>"""

# Handelsvolumen des Markts. Steht auf der Seite, weil die Mindestschwelle
# niedrig liegt: ein Preis aus 300 Dollar Umsatz sieht genauso aus wie einer
# aus 167'000, sagt aber etwas voellig anderes. Die Klasse "duenn" markiert
# die Faelle, bei denen das eine Rolle spielt.
VOLUMEN_VORLAGE = """      <span class="trenner">/</span>
      <span><<VOLUMEN_TEXT>></span>"""

# Farbvariable je Prognostiker. Ein nicht eingetragener Schluessel bekommt die
# neutrale Standardfarbe, statt die Legende unsichtbar zu machen.
MODELL_FARBE = {
    "claude": "claude",
    "openai": "gpt",
}


# --- Daten laden -----------------------------------------------------------

def lade_json(pfad):
    """Liest eine JSON-Datei (UTF-8). Fehlt sie, brechen wir klar ab."""
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except FileNotFoundError:
        print(
            f"Fehler: Datei {pfad} nicht gefunden. Bitte zuerst "
            f"fetch_markets.py und forecast.py ausfuehren.",
            file=sys.stderr,
        )
        sys.exit(1)


def baue_karten_daten(markets, forecasts):
    """Baut pro ausgewaehlter Frage einen Karten-Eintrag.

    Ausgangspunkt sind die Fragen, nicht die Prognosen. Beide Zahlen koennen
    unabhaengig voneinander fehlen: die Vergleichszahl, wenn der
    Community-Median gesperrt ist, und der Forecast, wenn eine Frage neu
    hinzugekommen ist und noch kein Prognose-Lauf darueber ging.
    """
    nach_id = {prognose["id"]: prognose for prognose in forecasts}

    eintraege = []
    for markt in markets:
        prognose = nach_id.get(markt["id"])
        market_p = markt.get("market_p")

        eintraege.append({
            "question": markt["question"],
            "source": markt.get("source", "unknown"),
            "benchmark_type": markt.get("benchmark_type", "market_price"),
            "category": markt.get("category", "other"),
            "country": markt.get("country", ""),
            "market_p": market_p,
            "resolve_time": markt.get("resolve_time", ""),
            "volume": markt.get("volume", 0.0),
            "url": markt.get("url", ""),
            "modelle": baue_modell_liste(prognose, market_p),
        })

    return eintraege


def baue_modell_liste(prognose, _market_p=None):
    """Baut pro Prognostiker einen Block mit Wert und Warnung.

    Feste Reihenfolge aus PROGNOSTIKER, damit die Spalten auf allen Eintraegen
    an derselben Stelle stehen. Fehlt ein Modell fuer diese Frage, kommt es
    trotzdem in die Liste - mit model_p None, damit der Eintrag den Platz
    freihaelt statt die Spalten zu verschieben.
    """
    vorhanden = (prognose or {}).get("forecasts") or {}

    modelle = []
    for schluessel, anzeigename, _modell_id in PROGNOSTIKER:
        eintrag = vorhanden.get(schluessel)

        modelle.append({
            "key": schluessel,
            "name": anzeigename,
            "model_p": eintrag["probability"] if eintrag else None,
            # Gesetzt, wenn Zahl und Begruendung sich widersprechen und auch
            # der Neuversuch das nicht aufgeloest hat (siehe pruefung.py).
            "flagged": eintrag.get("flagged") if eintrag else None,
        })

    return modelle


# --- Formatierung ----------------------------------------------------------

def formatiere_prozent(p):
    """Macht aus 0.72 die Anzeige "72%"."""
    return f"{round(p * 100)}%"


def position(p):
    """Position eines Punktes auf der Skala, in Prozent, als Text fuer CSS.

    Auf 1.5 bis 98.5 begrenzt: bei exakt 0 oder 100 haenge der halbe Punkt
    ausserhalb der Achse und waere angeschnitten.
    """
    return f"{min(max(p * 100, 1.5), 98.5):.1f}"


def formatiere_datum(iso_text):
    """Macht aus "2027-01-16T12:00:00Z" die Anzeige "16 Jan 2027".

    Ist der Text leer oder unlesbar, steht "date unknown" - besser als ein
    stillschweigend weggelassenes Feld, denn die Reihenfolge des Registers
    haengt genau an diesem Datum.
    """
    if not iso_text:
        return "date unknown"
    try:
        zeitpunkt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except ValueError:
        return "date unknown"
    return zeitpunkt.strftime("%d %b %Y")


def quellen_name(quelle):
    """Anzeigename einer Quelle, z. B. "polymarket" -> "Polymarket"."""
    return QUELLEN_NAMEN.get(quelle, quelle)


def kategorie_name(schluessel):
    """Anzeigename einer Kategorie, z. B. "elections" -> "Elections".

    Unbekannte Schluessel gehen unveraendert durch, statt zu verschwinden -
    eine neue Kategorie faellt so auf der Seite auf und wird nicht
    stillschweigend als "Other" ausgegeben.
    """
    for eintrag, anzeigename in KATEGORIE_NAMEN:
        if eintrag == schluessel:
            return anzeigename
    return schluessel


def benchmark_label(benchmark_type):
    """Beschriftung der Vergleichszahl, abhaengig von der Art des Benchmarks."""
    return BENCHMARK_LABEL.get(benchmark_type, "Benchmark")


# --- HTML bauen ------------------------------------------------------------

def baue_benchmark_block(eintrag):
    """Baut die Benchmark-Spalte: Zahl, oder ruhiger Hinweis auf ihr Fehlen."""
    label = benchmark_label(eintrag["benchmark_type"])

    if eintrag["market_p"] is None:
        hinweis = BENCHMARK_FEHLT.get(eintrag["benchmark_type"], "not available")
        return (
            BENCHMARK_FEHLT_VORLAGE
            .replace("<<BENCHMARK_LABEL>>", label)
            .replace("<<HINWEIS>>", hinweis)
        )

    return (
        BENCHMARK_VORLAGE
        .replace("<<BENCHMARK_LABEL>>", label)
        .replace("<<MARKT_P>>", formatiere_prozent(eintrag["market_p"]))
    )


def baue_ai_block(modell):
    """Baut die Spalte eines Prognostikers, oder den Hinweis, dass er fehlt.

    Die Differenz erscheint NUR, wenn beide Zahlen vorliegen. Eine Abweichung
    ohne Gegenwert waere eine Behauptung ohne Grundlage.
    """
    if modell["model_p"] is None:
        return (
            OHNE_AI_VORLAGE
            .replace("<<SCHLUESSEL>>", html.escape(modell["key"]))
            .replace("<<MODELL_NAME>>", html.escape(modell["name"]))
        )

    if modell.get("flagged"):
        warnung = WARNUNG_VORLAGE.replace(
            "<<GRUND>>",
            html.escape(f'reasoning contains "{modell["flagged"]}"'),
        )
    else:
        warnung = ""

    return (
        AI_VORLAGE
        .replace("<<SCHLUESSEL>>", html.escape(modell["key"]))
        .replace("<<MODELL_NAME>>", html.escape(modell["name"]))
        .replace("<<MODELL_P>>", formatiere_prozent(modell["model_p"]))
        .replace("<<WARNUNG>>", warnung)
    )


def baue_skala(eintrag):
    """Baut die gemeinsame Skala mit einem Punkt je vorhandener Schaetzung.

    Bleibt leer, solange weniger als zwei Punkte darauf liegen: eine Achse mit
    einem einzelnen Punkt zeigt keinen Vergleich, sondern nur eine Zahl, die
    zwei Zeilen darueber schon steht.
    """
    punkte = []

    if eintrag["market_p"] is not None:
        punkte.append((
            "bench",
            eintrag["market_p"],
            f'{benchmark_label(eintrag["benchmark_type"])} '
            f'{formatiere_prozent(eintrag["market_p"])}',
        ))

    for modell in eintrag["modelle"]:
        if modell["model_p"] is None:
            continue
        punkte.append((
            modell["key"],
            modell["model_p"],
            f'{modell["name"]} {formatiere_prozent(modell["model_p"])}',
        ))

    if len(punkte) < 2:
        return ""

    markierungen = "\n".join(
        PUNKT_VORLAGE
        .replace("<<SCHLUESSEL>>", html.escape(schluessel))
        .replace("<<POSITION>>", position(wert))
        .replace("<<TITEL>>", html.escape(titel))
        for schluessel, wert, titel in punkte
    )

    return SKALA_VORLAGE.replace("<<PUNKTE>>", markierungen)


def baue_volumen(eintrag):
    """Zeigt das Handelsvolumen eines Geldmarkts, sonst leeren Text.

    Nur fuer market_price: bei einem Community-Median waere "USD" schlicht
    falsch, dort zaehlen Prognostiker und keine Dollar.

    Die Zahl steht ohne Hervorhebung da. Eine farbige Markierung duenner
    Maerkte gab es kurzzeitig; sie wurde entfernt, weil eine zweite Farbe
    neben den drei Prognostiker-Farben mehr Fragen aufwarf als beantwortete.
    Die Einordnung leistet die Zahl selbst: 424 neben 168'000 ist deutlich
    genug.
    """
    if eintrag["benchmark_type"] != "market_price":
        return ""

    volumen = eintrag.get("volume") or 0
    if volumen <= 0:
        return ""

    # Erst ab 10'000 auf Tausender runden. Darunter steht die genaue Zahl:
    # "USD 3k traded" neben der Duenn-Markierung sah aus wie ein Fehler, weil
    # 2'999 und 3'400 beide als "3k" erscheinen, aber auf verschiedenen Seiten
    # der Schwelle liegen.
    if volumen >= 10000:
        text = f"USD {round(volumen / 1000):,}k traded"
    else:
        text = f"USD {round(volumen):,} traded"

    return VOLUMEN_VORLAGE.replace("<<VOLUMEN_TEXT>>", html.escape(text))


def baue_karte(eintrag, nummer):
    """Baut das HTML fuer einen einzelnen Register-Eintrag.

    nummer ist die laufende Nummer in der angezeigten Reihenfolge, zweistellig
    gesetzt. Sie macht das Register als geordnete Liste lesbar und gibt einen
    Bezugspunkt, wenn man ueber einen bestimmten Eintrag spricht.

    Alle Texte laufen durch html.escape. Der Fragetext stammt aus einer
    fremden API; ein "&" oder "<" darin wuerde die Seite sonst zerlegen.
    """
    land = eintrag["country"] or "Africa"

    return (
        KARTEN_VORLAGE
        .replace("<<NUMMER>>", f"{nummer:02d}")
        .replace("<<KATEGORIE_NAME>>", html.escape(kategorie_name(eintrag["category"])))
        .replace("<<KATEGORIE>>", html.escape(eintrag["category"]))
        .replace("<<QUELLE>>", html.escape(quellen_name(eintrag["source"])))
        .replace("<<LAND>>", html.escape(land))
        .replace("<<VOLUMEN>>", baue_volumen(eintrag))
        .replace("<<DATUM>>", html.escape(formatiere_datum(eintrag["resolve_time"])))
        .replace("<<FRAGE>>", html.escape(eintrag["question"]))
        .replace("<<BENCHMARK_BLOCK>>", baue_benchmark_block(eintrag))
        .replace("<<AI_BLOCK>>", "\n".join(baue_ai_block(m) for m in eintrag["modelle"]))
        .replace("<<SKALA>>", baue_skala(eintrag))
    )


def baue_tabs(eintraege):
    """Baut die Tab-Leiste aus den tatsaechlich vorhandenen Kategorien.

    Kategorien ohne Fragen bekommen keinen Tab: ein Tab, der auf eine leere
    Liste filtert, sieht nach einem Fehler aus.
    """
    tabs = [f'<button class="tab active" data-filter="all">All'
            f'<span class="zahl">{len(eintraege)}</span></button>']

    for schluessel, anzeigename in KATEGORIE_NAMEN:
        anzahl = sum(1 for e in eintraege if e["category"] == schluessel)
        if anzahl == 0:
            continue
        tabs.append(f'<button class="tab" data-filter="{schluessel}">{anzeigename}'
                    f'<span class="zahl">{anzahl}</span></button>')

    return "\n".join(tabs)


def baue_legende():
    """Baut die Farblegende der Prognostiker aus PROGNOSTIKER.

    Aus derselben Liste wie die Karten, damit ein dritter Prognostiker nicht
    auf den Karten auftaucht, in der Legende aber fehlt.
    """
    return "\n".join(
        LEGENDE_VORLAGE
        .replace("<<FARBE>>", MODELL_FARBE.get(schluessel, "modell-standard"))
        .replace("<<MODELL_NAME>>", html.escape(anzeigename))
        for schluessel, anzeigename, _modell_id in PROGNOSTIKER
    )


def nenne_modelle():
    """Nennt die tatsaechlich verwendeten Modelle mit ihrer ID.

    Aus den Konstanten der Prognostiker-Module gelesen, damit die Fusszeile
    bei einem Modellwechsel nicht stehen bleibt.
    """
    teile = [f"{html.escape(name)} (<code>{html.escape(modell)}</code>)"
             for _, name, modell in PROGNOSTIKER]
    if len(teile) == 1:
        return teile[0]
    return ", ".join(teile[:-1]) + " and " + teile[-1]


def benchmark_arten(eintraege):
    """Die tatsaechlich auf der Seite vorkommenden Benchmark-Arten.

    Eigene Funktion, weil zwei Stellen dieselbe Antwort brauchen: die Legende
    und der Fusszeilen-Absatz. Sie duerfen nie auseinanderlaufen - genau das
    war der Fehler, als die Legende noch fest "Market or community" sagte,
    obwohl es laengst nur noch Marktpreise gab.
    """
    return {e["benchmark_type"] for e in eintraege}


def legende_benchmark(eintraege):
    """Beschriftung der Benchmark-Farbe in der Legende."""
    if benchmark_arten(eintraege) == {"market_price"}:
        return "Market price"
    return "Market or community"


def nenne_quellen(eintraege):
    """Zaehlt die tatsaechlich vertretenen Quellen auf, z. B. "Metaculus and Polymarket"."""
    # sorted() gibt eine stabile Reihenfolge, damit die Fusszeile nicht bei
    # jedem Lauf anders aussieht und unnoetige Commits erzeugt.
    namen = sorted({quellen_name(e["source"]) for e in eintraege})

    if len(namen) == 1:
        return html.escape(namen[0])
    return html.escape(", ".join(namen[:-1]) + " and " + namen[-1])


# --- Reihenfolge -----------------------------------------------------------

def hat_prognose(eintrag):
    """True, wenn mindestens ein Modell fuer diese Frage geschaetzt hat."""
    return any(m["model_p"] is not None for m in eintrag["modelle"])


def sortierschluessel(eintrag):
    """Sortierung des Registers: naechste Aufloesung zuerst.

    Bewusst NICHT nach der Abweichung vom Benchmark. Diese Reihenfolge stellte
    die strittigsten Faelle nach oben und las sich dadurch wie eine Rangliste
    ("hier irrt der Markt am meisten") - eine Aussage, die durch nichts gedeckt
    ist, solange keine Frage aufgeloest ist. Das Aufloesungsdatum ist eine
    Eigenschaft der Frage und keine Wertung: oben steht, was als naechstes
    entschieden wird.

    Fragen ohne Datum kaemen bei reiner Textsortierung ans Ende - das ist auch
    die gewuenschte Stelle, darum genuegt der leere Text als Schluessel.
    """
    return eintrag.get("resolve_time") or "9999"


def baue_seite(eintraege, zeitstempel):
    """Setzt Kopf, Legende, Filterleiste, Register und Fusszeile zusammen."""
    sortiert = sorted(eintraege, key=sortierschluessel)
    eintraege_html = "\n".join(
        baue_karte(e, nummer) for nummer, e in enumerate(sortiert, start=1)
    )

    return (
        SEITEN_VORLAGE
        .replace("<<LEGENDE_MODELLE>>", baue_legende())
        .replace("<<MODELL_LISTE>>", nenne_modelle())
        .replace("<<ZEITSTEMPEL>>", zeitstempel)
        .replace("<<ANZAHL>>", str(len(sortiert)))
        .replace("<<TABS>>", baue_tabs(sortiert))
        .replace("<<KARTEN>>", eintraege_html)
        .replace("<<LEGENDE_BENCH>>", legende_benchmark(sortiert))
        .replace("<<QUELLEN_LISTE>>", nenne_quellen(sortiert))
        .replace("<<REPO_URL>>", REPO_URL)
    )


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_json(MARKETS_DATEI)
    forecasts = lade_json(FORECASTS_DATEI)

    eintraege = baue_karten_daten(markets, forecasts)
    if not eintraege:
        print(
            "Fehler: keine Frage in markets.json. Seite wird nicht geschrieben.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Bauzeit in UTC, direkt nach dem Abruf - der Stempel steht damit fuer den
    # Datenstand, nicht nur fuer den Zeitpunkt des Seitenbaus.
    zeitstempel = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    seite = baue_seite(eintraege, zeitstempel)

    AUSGABE_ORDNER.mkdir(exist_ok=True)
    with open(AUSGABE_DATEI, "w", encoding="utf-8") as datei:
        datei.write(seite)

    mit_prognose = sum(1 for e in eintraege if hat_prognose(e))
    mit_benchmark = sum(1 for e in eintraege if e["market_p"] is not None)
    print(f"{len(eintraege)} Karten nach {AUSGABE_DATEI} geschrieben "
          f"({mit_prognose} mit Prognose, {mit_benchmark} mit Vergleichszahl).")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
