"""build_site.py

Liest markets.json und forecasts.json und schreibt daraus eine statische
Seite docs/index.html. Kein Framework, keine zusaetzlichen Bibliotheken:
nur die Standardbibliothek, das Filtern uebernimmt etwas Vanilla-JS.

Ausgangspunkt sind die Fragen aus markets.json, nicht die Prognosen. Jede
ausgewaehlte Frage bekommt eine Karte mit der Vergleichszahl und beiden
Modellen. Jede dieser Zahlen kann fehlen, und jeder Fall hat eine eigene,
ruhige Darstellung - nie ein Pfeil ohne Zahl, nie eine leere Stelle.

Farbe bedeutet auf dieser Seite WER, nicht WAS: Benchmark, Claude und GPT
haben je eine feste Farbe, die in der Zahl, im Punkt auf der Skala und an der
Begruendung wiederkehrt. Die Kategorie traegt darum nur eine getoente Pille
und keine Kartenfarbe - zwei konkurrierende Farbsysteme auf einer Karte machen
beide unlesbar.

Das Kernstueck jeder Karte ist die gemeinsame Skala von 0 bis 100 Prozent, auf
der alle drei Schaetzungen als Punkte liegen. Drei getrennte grosse Zahlen
zwingen zum Kopfrechnen; auf einer Achse sieht man Uneinigkeit sofort.

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
<title>AI Forecasting: African Economic and Political Development</title>
<meta name="description" content="Two AI models forecast open questions on African
politics and economics, shown next to prediction-market prices.">
<style>
:root {
  --bg: #fbfbfa;
  --bg-akzent: #f4f4f2;
  --card: #ffffff;
  --text: #14171a;
  --text-soft: #4b535b;
  --muted: #7b848d;
  --line: #e3e5e8;
  --line-soft: #eeeff1;
  --link: #1a5fd0;

  /* Farbe bedeutet WER. Diese drei sind ueber die ganze Seite reserviert und
     tauchen nirgends in anderer Bedeutung auf. */
  --bench: #1d2530;      /* Benchmark: Tinte, er ist der Bezugspunkt */
  --claude: #b8552f;
  --gpt: #0e8f70;
  --modell-standard: #6b7280;   /* faengt einen dritten Prognostiker ohne Regel ab */

  --up: #12805c;
  --down: #c0392b;
  --flat: #8b949d;

  --schatten: 0 1px 2px rgba(16, 20, 24, .04), 0 2px 8px rgba(16, 20, 24, .04);
  --schatten-hover: 0 2px 4px rgba(16, 20, 24, .05), 0 8px 24px rgba(16, 20, 24, .09);

  --kat: #64748b;
  --kat-bg: #eef1f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b0d10;
    --bg-akzent: #12151a;
    --card: #14181e;
    --text: #eceff3;
    --text-soft: #b0b9c3;
    --muted: #828d99;
    --line: #242a33;
    --line-soft: #1b2028;
    --link: #6ba6ff;

    --bench: #dbe2ea;
    --claude: #e08a5f;
    --gpt: #35c9a2;
    --modell-standard: #9aa4b0;

    --up: #3ecf8e;
    --down: #ff6f61;
    --flat: #7d8792;

    --schatten: 0 1px 2px rgba(0, 0, 0, .5);
    --schatten-hover: 0 8px 28px rgba(0, 0, 0, .6);

    --kat: #94a3b8;
    --kat-bg: #1c232c;
  }
}

/* Kategorien: nur eine getoente Pille, keine Kartenfarbe. Sie ordnen ein,
   sie sind nicht die Aussage der Karte. */
.cat-elections { --kat: #1f5fd0; --kat-bg: #e9f0fd; }
.cat-security  { --kat: #b8460c; --kat-bg: #fbeade; }
.cat-diplomacy { --kat: #6b28c9; --kat-bg: #f0e9fd; }
.cat-economy   { --kat: #0d6f66; --kat-bg: #e2f2f0; }
.cat-other     { --kat: #5a6672; --kat-bg: #eef1f4; }
@media (prefers-color-scheme: dark) {
  .cat-elections { --kat: #7fb2ff; --kat-bg: #15243a; }
  .cat-security  { --kat: #fb9a4c; --kat-bg: #331f10; }
  .cat-diplomacy { --kat: #b195fb; --kat-bg: #241b3d; }
  .cat-economy   { --kat: #3ad4bd; --kat-bg: #0b2b28; }
  .cat-other     { --kat: #97a3b0; --kat-bg: #1c232c; }
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 0 1.15rem 4rem;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, "SF Pro Text", -apple-system, BlinkMacSystemFont,
               "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
.wrap { max-width: 1120px; margin: 0 auto; }

/* --- Kopf --- */
header.top {
  padding: 3.25rem 0 2rem;
  border-bottom: 1px solid var(--line);
  margin-bottom: 1.75rem;
}
.kicker {
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .16em;
  font-weight: 600;
  color: var(--muted);
  margin: 0 0 .85rem;
}
h1 {
  /* Serife nur fuer Ueberschrift und Fragetext. Sie trennt den Inhalt
     sichtbar von der Bedienoberflaeche, die serifenlos bleibt. */
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  font-size: clamp(1.85rem, 4.2vw, 2.7rem);
  line-height: 1.12;
  letter-spacing: -.018em;
  font-weight: 600;
  margin: 0 0 .7rem;
  max-width: 20ch;
}
.sub {
  color: var(--text-soft);
  margin: 0;
  max-width: 60ch;
  font-size: 1rem;
  line-height: 1.55;
}

/* Legende: erklaert das Farbsystem genau einmal */
.legende {
  display: flex;
  flex-wrap: wrap;
  gap: 1.1rem;
  margin: 1.75rem 0 0;
  font-size: .8rem;
  color: var(--text-soft);
}
.legende span { display: inline-flex; align-items: center; gap: .42rem; }
.swatch {
  width: .68rem;
  height: .68rem;
  border-radius: 50%;
  flex: none;
}

/* --- Steuerleiste --- */
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  margin: 0 0 1.15rem;
}
.tabs { display: flex; flex-wrap: wrap; gap: .35rem; }
.tab {
  font: inherit;
  font-size: .845rem;
  font-weight: 550;
  color: var(--text-soft);
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: .34rem .82rem;
  cursor: pointer;
  transition: background .13s, color .13s, border-color .13s;
}
.tab:hover { border-color: var(--kat); color: var(--text); }
.tab.active { background: var(--kat-bg); border-color: var(--kat); color: var(--kat); }
.tab[data-filter="all"].active {
  background: var(--text);
  border-color: var(--text);
  color: var(--bg);
}
.punkt {
  width: .44rem;
  height: .44rem;
  border-radius: 50%;
  background: var(--kat);
  display: inline-block;
  margin-right: .42rem;
  vertical-align: middle;
}
.tab .count { opacity: .55; margin-left: .34rem; font-variant-numeric: tabular-nums; }
.hinweis-sortierung { font-size: .76rem; color: var(--muted); }

/* --- Raster --- */
/* align-items bleibt auf dem Standard "stretch": Karten einer Zeile werden
   gleich hoch. Bei "start" endeten nebeneinanderliegende Karten je nach
   Laenge des Fragetexts auf unterschiedlicher Hoehe, was das Raster unruhig
   wirken liess. */
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .95rem;
}
/* Die Skala sitzt am unteren Rand jeder Karte (margin-top: auto weiter
   unten), damit sie in einer Zeile auf gleicher Hoehe liegt - egal ob der
   Fragetext zwei oder vier Zeilen braucht. Sie ist das Element, das man ueber
   die Karten hinweg vergleicht; verspringt es, vergleicht man schlechter. */
.card { display: flex; flex-direction: column; }
@media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }

/* --- Karte --- */
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 1.15rem 1.2rem 1.05rem;
  box-shadow: var(--schatten);
  transition: box-shadow .16s ease, transform .16s ease;
}
.card:hover { box-shadow: var(--schatten-hover); transform: translateY(-2px); }

.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .4rem;
  margin-bottom: .7rem;
}
.pill {
  font-size: .655rem;
  text-transform: uppercase;
  letter-spacing: .075em;
  font-weight: 650;
  border-radius: 999px;
  padding: .16rem .52rem;
  white-space: nowrap;
  color: var(--kat);
  background: var(--kat-bg);
}
.src {
  font-size: .7rem;
  font-weight: 550;
  color: var(--muted);
}
.geo { font-size: .74rem; color: var(--text-soft); margin-left: auto; white-space: nowrap; }

.q {
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  font-size: 1.03rem;
  font-weight: 500;
  line-height: 1.38;
  margin: 0 0 1rem;
  letter-spacing: -.004em;
}

/* Zahlenreihe. Jede Spalte traegt ihre Modellfarbe ueber --farbe. */
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
  gap: .55rem;
  /* Mindestabstand zur Skala. Der Rest des Platzes geht an margin-top: auto
     der Skala, die dadurch nach unten wandert. */
  margin-bottom: 1.1rem;
}
.m { min-width: 0; --farbe: var(--modell-standard); }
.m-bench { --farbe: var(--bench); }
.m-claude { --farbe: var(--claude); }
.m-openai { --farbe: var(--gpt); }
.lbl {
  display: flex;
  align-items: center;
  gap: .32rem;
  font-size: .655rem;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  font-weight: 650;
  margin-bottom: .2rem;
}
.lbl::before {
  content: "";
  width: .42rem;
  height: .42rem;
  border-radius: 50%;
  background: var(--farbe);
  flex: none;
}
.val {
  display: block;
  font-size: 1.72rem;
  font-weight: 680;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.03em;
  color: var(--farbe);
}
.leer {
  display: block;
  font-size: .85rem;
  color: var(--muted);
  font-style: italic;
  /* Gleiche Hoehe wie eine Zahl, damit die Spalten nicht verspringen, wenn
     nur ein Teil von ihnen belegt ist. */
  padding: .42rem 0 .5rem;
}

/* Gemeinsame Skala. Das eigentliche Bild der Karte: drei Punkte auf einer
   Achse, Abstand gleich Uneinigkeit. */
.skala {
  position: relative;
  height: 1.5rem;
  margin: auto 0 .2rem;
}
.track {
  position: absolute;
  top: .58rem;
  left: 0;
  right: 0;
  height: 3px;
  border-radius: 999px;
  background: var(--line);
}
.tick {
  position: absolute;
  top: .24rem;
  width: 1px;
  height: .72rem;
  background: var(--line);
  transform: translateX(-50%);
}
.tick-mitte { background: var(--line); opacity: 1; height: 1rem; top: .1rem; }
.mk {
  position: absolute;
  top: .22rem;
  width: .78rem;
  height: .78rem;
  border-radius: 50%;
  background: var(--farbe);
  /* Ring in der Kartenfarbe: liegen zwei Punkte fast uebereinander, bleiben
     sie trotzdem als zwei erkennbar. */
  box-shadow: 0 0 0 2.5px var(--card);
  transform: translateX(-50%);
}
.mk-bench { --farbe: var(--bench); z-index: 3; }
.mk-claude { --farbe: var(--claude); z-index: 2; }
.mk-openai { --farbe: var(--gpt); z-index: 1; }
.skala-achse {
  display: flex;
  justify-content: space-between;
  font-size: .62rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: .04em;
}

/* Widerspruch zwischen Zahl und Begruendung. Deutlich, aber nicht in der
   Farbe der Differenz - sonst liest man es als Richtungsangabe. */
.warnung {
  margin: .3rem 0 0;
  font-size: .7rem;
  font-weight: 600;
  color: #a8580a;
  cursor: help;
}
@media (prefers-color-scheme: dark) { .warnung { color: #f0a955; } }

footer {
  margin-top: 3rem;
  padding-top: 1.35rem;
  border-top: 1px solid var(--line);
  font-size: .81rem;
  color: var(--muted);
  max-width: 78ch;
  line-height: 1.6;
}
footer a { color: var(--link); text-decoration: none; }
footer a:hover { text-decoration: underline; }
footer p { margin: 0 0 .5rem; }
footer code {
  font-size: .93em;
  background: var(--bg-akzent);
  padding: .06em .32em;
  border-radius: 4px;
}
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <p class="kicker">Prediction markets &middot; Large language models</p>
  <h1>Can AI forecast African politics?</h1>
  <p class="sub">Two language models estimate the probability of open questions
  on African politics and economics. Neither ever sees the market price it is
  placed next to, so each estimate is an independent claim rather than a
  restatement of the crowd.</p>

  <div class="legende">
    <span><i class="swatch" style="background: var(--bench)"></i> Market or community benchmark</span>
<<LEGENDE_MODELLE>>
  </div>
</header>

<div class="controls">
  <nav class="tabs"><<TABS>></nav>
  <span class="hinweis-sortierung">Sorted by disagreement with the benchmark</span>
</div>

<div class="grid">
<<KARTEN>>
</div>

<footer>
<p>Forecasts come from <<MODELL_LISTE>>. Both receive the same question, the same
resolution criteria and the same web-search tool, with prediction-market sites
blocked. The benchmark is never passed into the prompt.</p>
<p>A Polymarket price reflects real money at stake; a Metaculus number is the
median of volunteer forecasts with nothing at risk. The two are labelled
differently for that reason. Where a benchmark is missing, the community median
is not available at this account&#39;s access tier.</p>
<p>Benchmarks from <<QUELLEN_LISTE>> &middot; last updated <<ZEITSTEMPEL>> &middot;
<a href="<<REPO_URL>>">source code and method</a></p>
</footer>

</div>

<script>
// Tab-Filter. Jede Karte traegt ihre Kategorie als data-category, jeder Tab
// den gewuenschten Filter als data-filter. Es wird nichts nachgeladen, wir
// blenden nur aus - ohne JavaScript bleiben darum alle Karten sichtbar.
document.querySelectorAll(".tab").forEach(function (tab) {
  tab.addEventListener("click", function () {
    var filter = tab.getAttribute("data-filter");

    document.querySelectorAll(".tab").forEach(function (anderer) {
      anderer.classList.remove("active");
    });
    tab.classList.add("active");

    document.querySelectorAll(".card").forEach(function (karte) {
      var passt = (filter === "all") || (karte.getAttribute("data-category") === filter);
      karte.style.display = passt ? "" : "none";
    });
  });
});
</script>
</body>
</html>
"""

KARTEN_VORLAGE = """<article class="card cat-<<KATEGORIE>>" data-category="<<KATEGORIE>>">
  <div class="card-head">
    <span class="pill"><<KATEGORIE_NAME>></span>
    <span class="src"><<QUELLE>></span>
    <span class="geo"><<LAND>></span>
  </div>
  <h3 class="q"><<FRAGE>></h3>
  <div class="metrics">
<<BENCHMARK_BLOCK>>
<<AI_BLOCK>>
  </div>
<<SKALA>>
</article>"""

BENCHMARK_VORLAGE = """    <div class="m m-bench">
      <span class="lbl"><<BENCHMARK_LABEL>></span>
      <span class="val"><<MARKT_P>></span>
    </div>"""

# Vergleichszahl fehlt: dieselbe Beschriftung, aber ein ruhiger Hinweis statt
# einer Zahl. Bewusst keine 0 und kein leerer Balken - beides waere eine
# Behauptung ueber einen Wert, den wir nicht haben.
BENCHMARK_FEHLT_VORLAGE = """    <div class="m m-bench">
      <span class="lbl"><<BENCHMARK_LABEL>></span>
      <span class="leer"><<HINWEIS>></span>
    </div>"""

# Auf der Karte steht nur die Zahl. Weder Konfidenz und Suchanzahl (Angaben
# ueber den Weg, nicht ueber das Ergebnis) noch die Differenz zum Benchmark:
# die Skala darunter zeigt den Abstand bereits als Bild, und dieselbe Aussage
# zweimal nebeneinander laesst die Karte voller wirken, ohne mehr zu sagen.
# Gespeichert bleibt alles in forecasts.json und in jeder Aufnahme.
AI_VORLAGE = """    <div class="m m-<<SCHLUESSEL>>">
      <span class="lbl"><<MODELL_NAME>></span>
      <span class="val"><<MODELL_P>></span>
<<WARNUNG>>
    </div>"""

OHNE_AI_VORLAGE = """    <div class="m m-<<SCHLUESSEL>>">
      <span class="lbl"><<MODELL_NAME>></span>
      <span class="leer">not forecast</span>
    </div>"""

# Warnung, wenn die Zahl der eigenen Begruendung widerspricht. Bewusst
# sichtbar auf der Karte: der Wert steht dann als grosse Abweichung weit oben,
# und ohne Hinweis liest man ihn als starke Modellaussage statt als Fehler.
WARNUNG_VORLAGE = """      <p class="warnung" title="<<GRUND>>">&#9888; contradicts its own reasoning</p>"""

SKALA_VORLAGE = """  <div class="skala">
    <div class="track"></div>
    <div class="tick" style="left: 25%"></div>
    <div class="tick tick-mitte" style="left: 50%"></div>
    <div class="tick" style="left: 75%"></div>
<<PUNKTE>>
  </div>
  <div class="skala-achse"><span>0%</span><span>50%</span><span>100%</span></div>"""

PUNKT_VORLAGE = """    <div class="mk mk-<<SCHLUESSEL>>" style="left: <<POSITION>>%" title="<<TITEL>>"></div>"""

LEGENDE_VORLAGE = """    <span><i class="swatch" style="background: var(--<<FARBE>>)"></i> <<MODELL_NAME>></span>"""

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
    Community-Median gesperrt ist, und der Forecast, wenn ein Lauf abgebrochen
    wurde. Die Differenz gibt es nur, wenn BEIDE vorliegen.
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
            "modelle": baue_modell_liste(prognose, market_p),
        })

    return eintraege


def baue_modell_liste(prognose, market_p):
    """Baut pro Prognostiker einen Block mit Wert, Abweichung und Begruendung.

    Feste Reihenfolge aus PROGNOSTIKER, damit die Spalten auf allen Karten an
    derselben Stelle stehen. Fehlt ein Modell fuer diese Frage, kommt es
    trotzdem in die Liste - mit model_p None, damit die Karte den Platz
    freihaelt statt die Spalten zu verschieben.
    """
    vorhanden = (prognose or {}).get("forecasts") or {}

    modelle = []
    for schluessel, anzeigename, _modell_id in PROGNOSTIKER:
        eintrag = vorhanden.get(schluessel)
        model_p = eintrag["probability"] if eintrag else None

        # Die Differenz steht nicht mehr auf der Karte, wird aber weiter
        # gebraucht: sie bestimmt die Reihenfolge der Karten und die
        # Kennzahl im Seitenkopf.
        if model_p is None or market_p is None:
            diff = None
        else:
            diff = round(model_p - market_p, 4)

        modelle.append({
            "key": schluessel,
            "name": anzeigename,
            "model_p": model_p,
            "diff": diff,
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


def baue_karte(eintrag):
    """Baut das HTML fuer eine einzelne Frage-Karte.

    Alle Texte laufen durch html.escape. Der Fragetext stammt aus einer
    fremden API; ein "&" oder "<" darin wuerde die Seite sonst zerlegen.
    """
    land = eintrag["country"] or "Africa"

    return (
        KARTEN_VORLAGE
        .replace("<<KATEGORIE_NAME>>", html.escape(kategorie_name(eintrag["category"])))
        .replace("<<KATEGORIE>>", html.escape(eintrag["category"]))
        .replace("<<QUELLE>>", html.escape(quellen_name(eintrag["source"])))
        .replace("<<LAND>>", html.escape(land))
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
            f'<span class="count">{len(eintraege)}</span></button>']

    for schluessel, anzeigename in KATEGORIE_NAMEN:
        anzahl = sum(1 for e in eintraege if e["category"] == schluessel)
        if anzahl == 0:
            continue
        tabs.append(f'<button class="tab cat-{schluessel}" data-filter="{schluessel}">'
                    f'<span class="punkt"></span>{anzeigename}'
                    f'<span class="count">{anzahl}</span></button>')

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


def nenne_quellen(eintraege):
    """Zaehlt die tatsaechlich vertretenen Quellen auf, z. B. "Metaculus and Polymarket"."""
    # sorted() gibt eine stabile Reihenfolge, damit die Fusszeile nicht bei
    # jedem Lauf anders aussieht und unnoetige Commits erzeugt.
    namen = sorted({quellen_name(e["source"]) for e in eintraege})

    if len(namen) == 1:
        return html.escape(namen[0])
    return html.escape(", ".join(namen[:-1]) + " and " + namen[-1])


# --- Kennzahlen ------------------------------------------------------------

def alle_diffs(eintrag):
    """Alle vorhandenen Abweichungen einer Karte, ueber alle Modelle."""
    return [m["diff"] for m in eintrag["modelle"] if m["diff"] is not None]


def hat_prognose(eintrag):
    """True, wenn mindestens ein Modell fuer diese Frage geschaetzt hat."""
    return any(m["model_p"] is not None for m in eintrag["modelle"])


def sortierschluessel(eintrag):
    """Sortierung der Karten.

    Drei Gruppen: erst Karten mit Vergleich, nach der GROESSTEN Abweichung
    eines ihrer Modelle - eine Karte, bei der ein Modell weit vom Benchmark
    abweicht, ist interessant, auch wenn das andere nahe dranliegt. Dann
    Karten mit Prognose, aber ohne Vergleichszahl. Zuletzt die noch offenen.
    """
    diffs = alle_diffs(eintrag)
    if diffs:
        return (0, -max(abs(d) for d in diffs))
    if hat_prognose(eintrag):
        return (1, 0.0)
    return (2, -(eintrag["market_p"] or 0))


def baue_seite(eintraege, zeitstempel):
    """Setzt Kopf, Legende, Tab-Leiste, Karten und Fusszeile zusammen."""
    sortiert = sorted(eintraege, key=sortierschluessel)

    return (
        SEITEN_VORLAGE
        .replace("<<LEGENDE_MODELLE>>", baue_legende())
        .replace("<<MODELL_LISTE>>", nenne_modelle())
        .replace("<<ZEITSTEMPEL>>", zeitstempel)
        .replace("<<TABS>>", baue_tabs(sortiert))
        .replace("<<KARTEN>>", "\n".join(baue_karte(e) for e in sortiert))
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
