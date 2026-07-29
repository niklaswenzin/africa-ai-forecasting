"""build_site.py

Liest markets.json und forecasts.json und schreibt daraus eine statische
Seite docs/index.html. Kein Framework, keine zusaetzlichen Bibliotheken:
nur die Standardbibliothek, das Filtern uebernimmt etwas Vanilla-JS.

Ausgangspunkt sind die Fragen aus markets.json, nicht die Prognosen. Jede
ausgewaehlte Frage bekommt eine Karte. Sowohl die Vergleichszahl als auch der
Claude-Forecast koennen fehlen, und beide Faelle haben eine eigene, ruhige
Darstellung - nie ein Pfeil ohne Zahl, nie eine leere Stelle.

Die Seite selbst ist auf Englisch, weil sie oeffentlich ist. Kommentare und
Funktionsnamen bleiben deutsch wie im Rest des Projekts.
"""

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Die Prognosen aufgeloester Fragen stehen nicht mehr in forecasts.json - sie
# kommen aus der Historie. brier.py hat die noetige Logik bereits (fruehester
# Snapshot mit Prognose je Frage), darum wird sie hier wiederverwendet statt
# ein zweites Mal geschrieben. So kann die Seite nie einen anderen
# Messzeitpunkt anzeigen, als der Brier Score verwendet.
import brier

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
RESOLVED_DATEI = Path("data") / "resolved.json"
AUSGABE_ORDNER = Path("docs")
AUSGABE_DATEI = AUSGABE_ORDNER / "index.html"

REPO_URL = "https://github.com/niklaswenzin/africa-ai-forecasting"

# Ab welcher Abweichung gilt Modell != Markt als nennenswert. Darunter zeigen
# wir die Differenz neutral grau an, damit Rauschen nicht wie ein Signal wirkt.
NAH_SCHWELLE = 0.05

QUELLEN_NAMEN = {
    "polymarket": "Polymarket",
    "metaculus": "Metaculus",
    "kalshi": "Kalshi",
}

# Beschriftung der Vergleichszahl. Ein Polymarket- oder Kalshi-Preis entsteht
# durch echten Geldeinsatz, der Metaculus-Wert ist der Median freiwilliger
# Community-Prognosen. Beides "Market" zu nennen waere irrefuehrend.
BENCHMARK_LABEL = {
    "market_price": "Market",
    "community_forecast": "Community",
}

# Text, wenn die Vergleichszahl fehlt. Haengt am benchmark_type, weil die
# Ursache unterschiedlich ist: bei Metaculus ist der Median gesperrt oder noch
# nicht freigegeben, bei einem Geldmarkt fehlt schlicht ein handelbarer Preis.
BENCHMARK_FEHLT = {
    "market_price": "No market price",
    "community_forecast": "Community forecast pending",
}

# Prognostiker in fester Reihenfolge: Schluessel in forecasts.json und
# Anzeigename auf der Karte. Ein dritter kaeme hier dazu, ohne dass die
# Karten-Vorlage angefasst werden muss.
PROGNOSTIKER = [
    ("claude", "Claude"),
    ("openai", "GPT"),
]

KATEGORIE_NAMEN = [
    ("elections", "Elections"),
    ("security", "Security"),
    ("diplomacy", "Diplomacy"),
    ("economy", "Economy"),
    ("other", "Other"),
]

# Flaggen-Emoji zum Laender-Tag. Die Schluessel sind exakt die Werte aus
# AFRIKA_LAND in fetch_markets.py. Somaliland und Sahel fehlen bewusst: fuer
# Somaliland gibt es kein Emoji (kein ISO-Laendercode), Sahel ist eine Region.
# Beide bekommen ueber den Standardwert die Weltkugel.
LAND_FLAGGE = {
    "South Sudan": "\U0001F1F8\U0001F1F8",
    "Guinea-Bissau": "\U0001F1EC\U0001F1FC",
    "Central African Republic": "\U0001F1E8\U0001F1EB",
    "South Africa": "\U0001F1FF\U0001F1E6",
    "Burkina Faso": "\U0001F1E7\U0001F1EB",
    "Sierra Leone": "\U0001F1F8\U0001F1F1",
    "Ivory Coast": "\U0001F1E8\U0001F1EE",
    "Nigeria": "\U0001F1F3\U0001F1EC",
    "Kenya": "\U0001F1F0\U0001F1EA",
    "Ethiopia": "\U0001F1EA\U0001F1F9",
    "Egypt": "\U0001F1EA\U0001F1EC",
    "Ghana": "\U0001F1EC\U0001F1ED",
    "Sudan": "\U0001F1F8\U0001F1E9",
    "Somalia": "\U0001F1F8\U0001F1F4",
    "Zimbabwe": "\U0001F1FF\U0001F1FC",
    "Uganda": "\U0001F1FA\U0001F1EC",
    "Tanzania": "\U0001F1F9\U0001F1FF",
    "Morocco": "\U0001F1F2\U0001F1E6",
    "Algeria": "\U0001F1E9\U0001F1FF",
    "Angola": "\U0001F1E6\U0001F1F4",
    "Senegal": "\U0001F1F8\U0001F1F3",
    "Rwanda": "\U0001F1F7\U0001F1FC",
    "Zambia": "\U0001F1FF\U0001F1F2",
    "Tunisia": "\U0001F1F9\U0001F1F3",
    "Libya": "\U0001F1F1\U0001F1FE",
    "Cameroon": "\U0001F1E8\U0001F1F2",
    "Gabon": "\U0001F1EC\U0001F1E6",
    "Mozambique": "\U0001F1F2\U0001F1FF",
    "Malawi": "\U0001F1F2\U0001F1FC",
    "Botswana": "\U0001F1E7\U0001F1FC",
    "Namibia": "\U0001F1F3\U0001F1E6",
    "Mauritania": "\U0001F1F2\U0001F1F7",
    "Liberia": "\U0001F1F1\U0001F1F7",
    "Congo": "\U0001F1E8\U0001F1EC",
    "Mali": "\U0001F1F2\U0001F1F1",
    "Niger": "\U0001F1F3\U0001F1EA",
    "Togo": "\U0001F1F9\U0001F1EC",
    "Benin": "\U0001F1E7\U0001F1EF",
    "Eritrea": "\U0001F1EA\U0001F1F7",
    "Djibouti": "\U0001F1E9\U0001F1EF",
    "Madagascar": "\U0001F1F2\U0001F1EC",
    "Lesotho": "\U0001F1F1\U0001F1F8",
    "Eswatini": "\U0001F1F8\U0001F1FF",
}
FLAGGE_STANDARD = "\U0001F30D"   # Weltkugel Afrika/Europa


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
<style>
:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --text: #101418;
  --text-soft: #4a545e;
  --muted: #79838d;
  --line: #e4e7eb;
  --line-soft: #eef0f3;
  --accent: #1f6feb;
  --up: #12805c;
  --down: #c0392b;
  --flat: #79838d;
  --bar: #e4e7eb;
  --bar-fill: #1f6feb;
  --schatten: 0 1px 2px rgba(16, 20, 24, .05), 0 1px 3px rgba(16, 20, 24, .04);
  --schatten-hover: 0 3px 10px rgba(16, 20, 24, .09);
  /* Standard-Kategorienfarbe. Faengt eine Kategorie ab, fuer die es unten
     keine Regel gibt - ohne diesen Wert waere var(--kat) ungueltig und die
     Akzentlinie der Karte verschwaende oder erbte eine zufaellige Farbe. */
  --kat: #64748b;
  --kat-bg: #eef1f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0c0f13;
    --card: #151a20;
    --text: #e9eef4;
    --text-soft: #b3bdc7;
    --muted: #8592a0;
    --line: #262d36;
    --line-soft: #1d232b;
    --accent: #5aa2ff;
    --up: #3ecf8e;
    --down: #ff6b5e;
    --flat: #8592a0;
    --bar: #262d36;
    --bar-fill: #5aa2ff;
    --schatten: 0 1px 2px rgba(0, 0, 0, .4);
    --schatten-hover: 0 3px 12px rgba(0, 0, 0, .55);
    --kat: #94a3b8;
    --kat-bg: #1c232c;
  }
}
/* Kategorienfarben. Jede Kategorie setzt --kat (kraeftig, fuer Text, Rahmen
   und Akzentlinie) und --kat-bg (getoent, fuer Flaechen). Beides wird von
   Karte und Tab geerbt, die Regeln weiter unten greifen dadurch auf
   dieselben zwei Variablen zu.

   Bewusst KEIN Rot fuer Security und KEIN Gruen fuer Economy: diese beiden
   Farben bedeuten auf der Seite bereits "Modell ueber bzw. unter dem
   Benchmark". Eine Farbe mit zwei Bedeutungen macht beide unlesbar, darum
   Orange und Teal. */
.cat-elections { --kat: #1f6feb; --kat-bg: #e8f0fe; }
.cat-security  { --kat: #c2410c; --kat-bg: #fcebdf; }
.cat-diplomacy { --kat: #6d28d9; --kat-bg: #efe8fd; }
.cat-economy   { --kat: #0f766e; --kat-bg: #e0f2f0; }
.cat-other     { --kat: #64748b; --kat-bg: #eef1f4; }
@media (prefers-color-scheme: dark) {
  .cat-elections { --kat: #6cabff; --kat-bg: #14243a; }
  .cat-security  { --kat: #fb923c; --kat-bg: #33200f; }
  .cat-diplomacy { --kat: #a78bfa; --kat-bg: #241a3d; }
  .cat-economy   { --kat: #2dd4bf; --kat-bg: #0c2b28; }
  .cat-other     { --kat: #94a3b8; --kat-bg: #1c232c; }
}

* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2.25rem 1.15rem 3rem;
  background: var(--bg);
  color: var(--text);
  /* Inter zuerst, aber ohne Web-Font-Download: wer sie installiert hat,
     bekommt sie, alle anderen den System-Stack. Kein externer Request. */
  font-family: Inter, "SF Pro Text", -apple-system, BlinkMacSystemFont,
               "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1020px; margin: 0 auto; }

/* Kopf */
header { margin-bottom: 1.5rem; }
h1 {
  font-size: 1.55rem;
  line-height: 1.2;
  letter-spacing: -.021em;
  font-weight: 700;
  margin: 0 0 .35rem;
}
.sub {
  color: var(--text-soft);
  margin: 0 0 1rem;
  max-width: 62ch;
  font-size: .93rem;
}
.stats { display: flex; flex-wrap: wrap; gap: .5rem; }
.stat {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .45rem .75rem;
  box-shadow: var(--schatten);
  display: flex;
  align-items: baseline;
  gap: .4rem;
}
.stat-value { font-size: 1.02rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat-label {
  font-size: .69rem;
  text-transform: uppercase;
  letter-spacing: .065em;
  color: var(--muted);
  font-weight: 600;
}

/* Tabs als Pills */
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: .38rem;
  margin: 1.35rem 0 1.15rem;
}
.tab {
  font: inherit;
  font-size: .845rem;
  font-weight: 550;
  color: var(--text-soft);
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: .34rem .8rem;
  cursor: pointer;
  transition: background .12s, color .12s, border-color .12s;
}
.tab:hover { border-color: var(--kat, var(--muted)); color: var(--text); }
/* Aktiver Kategorie-Tab: getoente Flaeche, Text und Rahmen in der Kategorien-
   farbe. Bewusst nicht die kraeftige Farbe als Hintergrund mit weisser
   Schrift - das haette im Dunkelmodus zu wenig Kontrast, weil --kat dort
   selbst hell ist. */
.tab.active {
  background: var(--kat-bg);
  border-color: var(--kat);
  color: var(--kat);
}
/* Der All-Tab gehoert zu keiner Kategorie und bleibt darum neutral invertiert. */
.tab[data-filter="all"].active {
  background: var(--text);
  border-color: var(--text);
  color: var(--bg);
}
.punkt {
  width: .45rem;
  height: .45rem;
  border-radius: 50%;
  background: var(--kat);
  display: inline-block;
  margin-right: .4rem;
  vertical-align: middle;
}
.tab .count { opacity: .6; margin-left: .32rem; font-variant-numeric: tabular-nums; }

/* Grid: zwei breite Spalten statt drei schmaler. Die Fragetexte sind lang
   ("Will Platforma Reupblicana No Kumpu Guine win the most seats in the 2025
   Guinea-Bissau National People's Assembly election?") und brachen in drei
   Spalten auf fuenf Zeilen um. */
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: .85rem;
  align-items: start;
}
@media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }

/* Karte */
.card {
  background: var(--card);
  border: 1px solid var(--line);
  /* Akzentlinie oben in der Kategorienfarbe. Sie traegt dieselbe Information
     wie die Pille im Kartenkopf, aber ueber die ganze Breite - dadurch sind
     Bloecke gleicher Kategorie im Grid auf einen Blick als Gruppe erkennbar. */
  border-top: 3px solid var(--kat);
  border-radius: 11px;
  padding: 1rem;
  box-shadow: var(--schatten);
  transition: box-shadow .15s ease, transform .15s ease, border-color .15s ease;
}
.card:hover {
  box-shadow: var(--schatten-hover);
  border-color: var(--line);
  border-top-color: var(--kat);
  transform: translateY(-1px);
}
.card-head { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .6rem; }
.badge, .tag {
  font-size: .655rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  font-weight: 650;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: .12rem .48rem;
  white-space: nowrap;
}
.tag { text-transform: none; letter-spacing: .01em; font-size: .7rem; }
/* Kategorienpille: die Farbe allein waere kryptisch, hier steht der Name dazu. */
.cat-pill {
  color: var(--kat);
  background: var(--kat-bg);
  border-color: transparent;
}
.question {
  font-weight: 600;
  font-size: .94rem;
  line-height: 1.38;
  margin: 0 0 .85rem;
  letter-spacing: -.005em;
}

/* Zahlenblock: Benchmark und Claude nebeneinander statt untereinander. Die
   breiteren Karten machen den direkten Vergleich moeglich - beide Zahlen auf
   einer Hoehe, das Auge muss nicht mehr springen. */
/* auto-fit statt fester Spaltenzahl: kommt ein dritter Prognostiker dazu,
   ordnet sich das Raster selbst neu, ohne dass das CSS angefasst wird. */
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(105px, 1fr));
  gap: .8rem;
}
.metric-col { min-width: 0; }
.metric-col + .metric-col {
  border-left: 1px solid var(--line-soft);
  padding-left: .8rem;
}
.metric-label {
  display: block;
  font-size: .665rem;
  text-transform: uppercase;
  letter-spacing: .07em;
  color: var(--muted);
  font-weight: 650;
  margin-bottom: .18rem;
}
.metric-value {
  font-size: 1.95rem;
  font-weight: 700;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.025em;
  display: block;
}
.bar {
  height: 5px;
  background: var(--bar);
  border-radius: 999px;
  overflow: hidden;
  margin: .5rem 0 0;
}
.bar-fill { height: 100%; background: var(--bar-fill); border-radius: 999px; }

.diff {
  display: block;
  font-size: .84rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  margin-top: .28rem;
}
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--flat); }

/* Leere Zustaende: ruhig, aber nie eine Luecke */
.leer {
  display: block;
  font-size: .82rem;
  color: var(--muted);
  font-style: italic;
  /* Gleiche Hoehe wie eine Zahl, damit die beiden Spalten nicht verspringen,
     wenn nur eine von beiden belegt ist. */
  padding: .5rem 0 .35rem;
}
.meta { margin: .4rem 0 0; font-size: .755rem; color: var(--muted); }
/* Widerspruch zwischen Zahl und Begruendung. Deutlich, aber nicht in der
   Farbe der Differenz-Pfeile - sonst liest man es als Richtungsangabe. */
.warnung {
  margin: .35rem 0 0;
  font-size: .72rem;
  font-weight: 600;
  color: #b45309;
  cursor: help;
}
@media (prefers-color-scheme: dark) { .warnung { color: #f0a955; } }

details { margin-top: .85rem; border-top: 1px solid var(--line-soft); padding-top: .6rem; }
summary {
  cursor: pointer;
  font-size: .78rem;
  color: var(--accent);
  font-weight: 550;
}
details p { margin: .55rem 0 0; font-size: .85rem; color: var(--text-soft); }
/* Modellname ueber der jeweiligen Begruendung - ohne ihn waeren die beiden
   Absaetze nicht auseinanderzuhalten. */
.reason-head {
  font-size: .68rem !important;
  text-transform: uppercase;
  letter-spacing: .07em;
  font-weight: 650;
  color: var(--muted) !important;
  margin-top: .8rem !important;
}
details .criteria {
  margin: .55rem 0 0;
  font-size: .78rem;
  color: var(--muted);
  white-space: pre-wrap;
}

/* Aufgeloeste Fragen: bewusst als Tabelle, nicht als Karten. Hier zaehlt der
   Vergleich Zeile fuer Zeile, nicht die einzelne Frage. */
.resolved { margin-top: 2.5rem; }
.resolved h2 {
  font-size: 1.1rem;
  margin: 0 0 .3rem;
  letter-spacing: -.01em;
}
.resolved h2 .count {
  font-size: .8rem;
  color: var(--muted);
  font-weight: 500;
  margin-left: .3rem;
}
.resolved .sub { font-size: .82rem; margin-bottom: .8rem; }
/* Auf schmalen Schirmen scrollt die Tabelle in ihrem eigenen Kasten,
   damit die Seite selbst nie seitlich wandert. */
.resolved table {
  width: 100%;
  border-collapse: collapse;
  font-size: .84rem;
  display: block;
  overflow-x: auto;
}
.resolved th {
  text-align: left;
  font-size: .67rem;
  text-transform: uppercase;
  letter-spacing: .07em;
  color: var(--muted);
  font-weight: 650;
  padding: 0 .7rem .4rem 0;
  white-space: nowrap;
}
.resolved td {
  padding: .5rem .7rem .5rem 0;
  border-top: 1px solid var(--line);
  vertical-align: top;
}
.resolved .frage { min-width: 20rem; }
.resolved .zahl { white-space: nowrap; font-variant-numeric: tabular-nums; }
.resolved .datum { color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.resolved .brier { color: var(--muted); font-size: .76rem; margin-left: .3rem; }
.outcome {
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  font-weight: 650;
  border-radius: 999px;
  padding: .12rem .5rem;
  white-space: nowrap;
}
.outcome.ja { color: var(--up); border: 1px solid var(--up); }
.outcome.nein { color: var(--down); border: 1px solid var(--down); }

footer {
  margin-top: 2.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
  font-size: .8rem;
  color: var(--muted);
  max-width: 80ch;
}
footer a { color: var(--accent); }
footer p { margin: 0 0 .35rem; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>AI Forecasting: African Economic and Political Development</h1>
  <p class="sub">Claude estimates the probability of open questions on African
  politics and economics, without ever seeing the benchmark it is compared against.</p>
  <div class="stats">
    <div class="stat"><span class="stat-value"><<ANZAHL>></span><span class="stat-label">Questions</span></div>
    <div class="stat"><span class="stat-value"><<ANZAHL_QUELLEN>></span><span class="stat-label">Sources</span></div>
    <div class="stat"><span class="stat-value"><<DURCHSCHNITT>></span><span class="stat-label">Avg. gap</span></div>
  </div>
</header>

<nav class="tabs"><<TABS>></nav>

<div class="grid">
<<KARTEN>>
</div>

<<AUFGELOEST>>

<footer>
<p>Forecasts come from the Claude API (<code>claude-sonnet-4-6</code>) with optional
web search; the benchmark is never passed into the prompt, so the estimate is
independent rather than a restatement of the market.</p>
<p>Benchmarks from <<QUELLEN_LISTE>> &middot; last updated <<ZEITSTEMPEL>> &middot;
<a href="<<REPO_URL>>">source and method</a></p>
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
    <span class="badge cat-pill"><<KATEGORIE_NAME>></span>
    <span class="badge"><<QUELLE>></span>
    <span class="tag"><<FLAGGE>> <<LAND>></span>
  </div>
  <p class="question"><<FRAGE>></p>
  <div class="metrics">
<<BENCHMARK_BLOCK>>
<<AI_BLOCK>>
  </div>
  <details>
    <summary>Details</summary>
<<REASONING_BLOCK>>
    <p class="criteria"><<KRITERIEN>></p>
  </details>
</article>"""

# Vergleichszahl vorhanden: grosse Zahl, darunter der Balken.
BENCHMARK_VORLAGE = """    <div class="metric-col">
      <span class="metric-label"><<BENCHMARK_LABEL>></span>
      <span class="metric-value"><<MARKT_P>></span>
      <div class="bar"><div class="bar-fill" style="width: <<BALKEN>>%"></div></div>
    </div>"""

# Vergleichszahl fehlt: dieselbe Beschriftung, aber ein ruhiger Hinweis statt
# einer Zahl - und kein Balken, denn ein leerer Balken suggeriert 0 Prozent.
BENCHMARK_FEHLT_VORLAGE = """    <div class="metric-col">
      <span class="metric-label"><<BENCHMARK_LABEL>></span>
      <span class="leer"><<HINWEIS>></span>
    </div>"""

AI_VORLAGE = """    <div class="metric-col">
      <span class="metric-label"><<MODELL_NAME>></span>
      <span class="metric-value"><<MODELL_P>></span>
<<DIFF_BLOCK>>
      <p class="meta"><<CONFIDENCE>> &middot; <<SUCHE>></p>
<<WARNUNG>>
    </div>"""

# Warnung, wenn die Zahl der eigenen Begruendung widerspricht. Bewusst
# sichtbar auf der Karte: der Wert steht dann als grosse Abweichung weit oben,
# und ohne Hinweis liest man ihn als starke Modellaussage statt als Fehler.
WARNUNG_VORLAGE = """      <p class="warnung" title="<<GRUND>>">&#9888; number contradicts the reasoning</p>"""

DIFF_VORLAGE = """      <span class="diff <<DIFF_KLASSE>>"><<DIFF>></span>"""

OHNE_AI_VORLAGE = """    <div class="metric-col">
      <span class="metric-label"><<MODELL_NAME>></span>
      <span class="leer">Not yet</span>
    </div>"""

# Abschnitt fuer aufgeloeste Fragen. Wird nur eingesetzt, wenn es welche gibt -
# eine leere Ueberschrift "Resolved" mit nichts darunter saehe nach einem
# Fehler aus.
AUFGELOEST_VORLAGE = """<section class="resolved">
  <h2>Resolved <span class="count"><<ANZAHL>></span></h2>
  <p class="sub">Scored against the earliest snapshot that held a forecast, so
  model and benchmark are judged on the same information. Lower Brier is better;
  0.25 is what a constant 50&#37; guess scores.</p>
  <table>
    <thead>
      <tr><th>Question</th><th>Outcome</th><<KOEPFE>><th>Benchmark</th><th>Measured</th></tr>
    </thead>
    <tbody>
<<ZEILEN>>
    </tbody>
  </table>
</section>"""

AUFGELOEST_ZEILE = """      <tr>
        <td class="frage"><<FRAGE>></td>
        <td><span class="outcome <<OUTCOME_KLASSE>>"><<OUTCOME>></span></td>
<<ZELLEN>>
        <td class="zahl"><<BENCH>></td>
        <td class="datum"><<DATUM>></td>
      </tr>"""

# Eine Zelle je Prognostiker: Schaetzung von damals und ihr Brier Score.
AUFGELOEST_ZELLE = """        <td class="zahl"><<WERT>></td>"""

# Begruendung je Modell im aufklappbaren Teil. Beide stehen untereinander,
# damit man sie direkt vergleichen kann - dort liegt der eigentliche
# Erkenntniswert, nicht in den zwei Prozentzahlen.
REASONING_VORLAGE = """    <p class="reason-head"><<MODELL_NAME>></p>
    <p><<REASONING>></p>"""


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


def lade_json_optional(pfad, standard):
    """Liest eine JSON-Datei, oder gibt den Standardwert zurueck.

    Anders als lade_json ist eine fehlende Datei hier kein Abbruchgrund: eine
    Seite ohne aufgeloeste Fragen ist der Normalfall, solange nichts
    aufgeloest ist.
    """
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError):
        return standard


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
        modelle = baue_modell_liste(prognose, market_p)

        eintraege.append({
            "question": markt["question"],
            "source": markt.get("source", "unknown"),
            "benchmark_type": markt.get("benchmark_type", "market_price"),
            "category": markt.get("category", "other"),
            "country": markt.get("country", ""),
            "market_p": market_p,
            "modelle": modelle,
            "criteria": markt.get("description", ""),
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
    for schluessel, anzeigename in PROGNOSTIKER:
        eintrag = vorhanden.get(schluessel)
        model_p = eintrag["probability"] if eintrag else None

        if model_p is None or market_p is None:
            diff = None
        else:
            diff = round(model_p - market_p, 4)

        modelle.append({
            "key": schluessel,
            "name": anzeigename,
            "model_p": model_p,
            "diff": diff,
            "confidence": eintrag["confidence"] if eintrag else "",
            "reasoning": eintrag["reasoning"] if eintrag else "",
            "searched": eintrag.get("searched", False) if eintrag else False,
            "num_searches": eintrag.get("num_searches", 0) if eintrag else 0,
            # Gesetzt, wenn Zahl und Begruendung sich widersprechen und auch
            # der Neuversuch das nicht aufgeloest hat (siehe pruefung.py).
            "flagged": eintrag.get("flagged") if eintrag else None,
        })

    return modelle


def baue_aufgeloeste_daten():
    """Baut die Eintraege fuer aufgeloeste Fragen, aelteste Aufloesung zuletzt.

    Gezeigt wird der Stand vom MESSZEITPUNKT, nicht der letzte bekannte: also
    die frueheste Aufnahme mit einer Prognose zu dieser Frage, und die
    Vergleichszahl aus derselben Aufnahme. Genau so rechnet brier.py, und
    genau darum darf die Seite es nicht anders machen - sonst stuenden auf der
    Karte andere Zahlen als im Score.

    Nur Fragen mit tatsaechlich bekanntem Ausgang. "void" (annulliert) und
    "unavailable" (Quelle gibt den Ausgang nicht her, siehe
    resolve_questions.py) haben keinen Ausgang und gehoeren nicht in eine
    Trefferliste.
    """
    aufgeloest = lade_json_optional(RESOLVED_DATEI, [])
    if not aufgeloest:
        return []

    prognosen = brier.erste_prognosen(brier.lade_aufnahmen())

    eintraege = []
    for eintrag in aufgeloest:
        if eintrag.get("status") != "resolved":
            continue
        ausgang = eintrag.get("outcome")
        if ausgang not in (0, 1):
            continue

        gemessen = prognosen.get(eintrag["id"])
        if gemessen is None:
            # Aufgeloest, aber nie mit einer Prognose gesehen. Anzeigen waere
            # irrefuehrend: es gaebe nichts zu bewerten.
            continue

        modelle = []
        for schluessel, anzeigename in PROGNOSTIKER:
            prognose = gemessen["forecasts"].get(schluessel)
            p = prognose.get("probability") if prognose else None
            modelle.append({
                "name": anzeigename,
                "model_p": p,
                "brier": None if p is None else round(brier.brier_einzeln(p, ausgang), 4),
            })

        market_p = gemessen.get("market_p")
        eintraege.append({
            "question": eintrag.get("question", ""),
            "source": eintrag.get("source", "unknown"),
            "outcome": ausgang,
            "measured_at": (gemessen.get("taken_at") or "")[:10],
            "market_p": market_p,
            "market_brier": (None if market_p is None
                             else round(brier.brier_einzeln(market_p, ausgang), 4)),
            "modelle": modelle,
        })

    # Zuletzt Gemessenes zuerst: die juengste Aufloesung ist die interessante.
    eintraege.sort(key=lambda e: e["measured_at"], reverse=True)
    return eintraege


# --- Formatierung ----------------------------------------------------------

def formatiere_prozent(p):
    """Macht aus 0.72 die Anzeige "72%"."""
    return f"{round(p * 100)}%"


def balken_breite(p):
    """Breite des Wahrscheinlichkeitsbalkens in Prozent, als Text fuer CSS."""
    return str(round(p * 100))


def formatiere_diff(diff):
    """Formatiert die Differenz mit Pfeil, z. B. "&#9650; 46 pts".

    Rundet die Differenz auf 0 Punkte, waere "0 pts" irrefuehrend (der Wert
    ist nicht exakt null), darum "<1 pt". Bei genau einem Punkt "pt".
    """
    punkte = round(diff * 100)
    if punkte == 0:
        return "&#9679; &lt;1 pt"

    pfeil = "&#9650;" if punkte > 0 else "&#9660;"
    einheit = "pt" if abs(punkte) == 1 else "pts"
    return f"{pfeil} {abs(punkte)} {einheit}"


def klasse_fuer_diff(diff):
    """CSS-Klasse (Farbe) fuer die Differenz.

    Abweichungen unterhalb von NAH_SCHWELLE zeigen wir neutral grau, damit
    kleine Unterschiede optisch nicht wie eine echte Gegenposition wirken.
    """
    if abs(diff) < NAH_SCHWELLE:
        return "flat"
    return "up" if diff > 0 else "down"


def quellen_name(quelle):
    """Anzeigename einer Quelle, z. B. "polymarket" -> "Polymarket"."""
    return QUELLEN_NAMEN.get(quelle, quelle)


def kategorie_name(schluessel):
    """Anzeigename einer Kategorie, z. B. "elections" -> "Elections".

    Unbekannte Schluessel gehen unveraendert durch, statt zu verschwinden -
    eine neue Kategorie faellt so auf der Seite auf und wird nicht stillschweigend
    als "Other" ausgegeben.
    """
    for eintrag, anzeigename in KATEGORIE_NAMEN:
        if eintrag == schluessel:
            return anzeigename
    return schluessel


def benchmark_label(benchmark_type):
    """Beschriftung der Vergleichszahl, abhaengig von der Art des Benchmarks."""
    return BENCHMARK_LABEL.get(benchmark_type, "Benchmark")


def flagge_fuer_land(land):
    """Flaggen-Emoji zum Land, sonst die Weltkugel.

    Unbekannte oder regionale Angaben (Somaliland, Sahel) bekommen bewusst
    einen neutralen Standardwert, statt gar kein Zeichen - so bleibt der Tag
    optisch gleich breit aufgebaut.
    """
    return LAND_FLAGGE.get(land, FLAGGE_STANDARD)


def beschreibe_suche(eintrag):
    """Formuliert den Hinweis, ob und wie oft das Modell gesucht hat."""
    if not eintrag["searched"]:
        return "no web search"
    anzahl = eintrag["num_searches"]
    return f"{anzahl} web search{'es' if anzahl != 1 else ''}"


# --- HTML bauen ------------------------------------------------------------

def baue_benchmark_block(eintrag):
    """Baut den Benchmark-Teil: grosse Zahl mit Balken, oder ruhiger Hinweis."""
    label = benchmark_label(eintrag["benchmark_type"])

    if eintrag["market_p"] is None:
        hinweis = BENCHMARK_FEHLT.get(eintrag["benchmark_type"], "Not available")
        return (
            BENCHMARK_FEHLT_VORLAGE
            .replace("<<BENCHMARK_LABEL>>", label)
            .replace("<<HINWEIS>>", hinweis)
        )

    return (
        BENCHMARK_VORLAGE
        .replace("<<BENCHMARK_LABEL>>", label)
        .replace("<<MARKT_P>>", formatiere_prozent(eintrag["market_p"]))
        .replace("<<BALKEN>>", balken_breite(eintrag["market_p"]))
    )


def baue_ai_block(modell):
    """Baut die Spalte eines Prognostikers, oder den Hinweis, dass er fehlt.

    Der Differenz-Pfeil erscheint NUR, wenn beide Zahlen vorliegen. Ein Pfeil
    ohne Gegenwert waere eine Behauptung ohne Grundlage.
    """
    if modell["model_p"] is None:
        return OHNE_AI_VORLAGE.replace("<<MODELL_NAME>>", html.escape(modell["name"]))

    if modell["diff"] is None:
        diff_block = ""
    else:
        diff_block = (
            DIFF_VORLAGE
            .replace("<<DIFF_KLASSE>>", klasse_fuer_diff(modell["diff"]))
            .replace("<<DIFF>>", formatiere_diff(modell["diff"]))
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
        .replace("<<MODELL_NAME>>", html.escape(modell["name"]))
        .replace("<<MODELL_P>>", formatiere_prozent(modell["model_p"]))
        .replace("<<DIFF_BLOCK>>", diff_block)
        .replace("<<CONFIDENCE>>", html.escape(modell["confidence"]))
        .replace("<<SUCHE>>", beschreibe_suche(modell))
        .replace("<<WARNUNG>>", warnung)
    )


def baue_reasoning_block(eintrag):
    """Baut die Begruendungen aller Modelle, die eine geliefert haben."""
    teile = []
    for modell in eintrag["modelle"]:
        if not modell["reasoning"]:
            continue
        teile.append(
            REASONING_VORLAGE
            .replace("<<MODELL_NAME>>", html.escape(modell["name"]))
            .replace("<<REASONING>>", html.escape(modell["reasoning"]))
        )
    return "\n".join(teile)


def baue_karte(eintrag):
    """Baut das HTML fuer eine einzelne Frage-Karte.

    Alle Texte laufen durch html.escape. Frage, Begruendung und Kriterien
    stammen aus fremden APIs bzw. vom Modell; ein "&" oder "<" darin wuerde
    die Seite sonst zerlegen.
    """
    kriterien = eintrag["criteria"].strip() or "No resolution criteria provided."
    reasoning_block = baue_reasoning_block(eintrag)
    ai_bloecke = "\n".join(baue_ai_block(m) for m in eintrag["modelle"])
    land = eintrag["country"] or "Africa"

    return (
        KARTEN_VORLAGE
        .replace("<<KATEGORIE_NAME>>", html.escape(kategorie_name(eintrag["category"])))
        .replace("<<KATEGORIE>>", html.escape(eintrag["category"]))
        .replace("<<QUELLE>>", html.escape(quellen_name(eintrag["source"])))
        .replace("<<FLAGGE>>", flagge_fuer_land(land))
        .replace("<<LAND>>", html.escape(land))
        .replace("<<FRAGE>>", html.escape(eintrag["question"]))
        .replace("<<BENCHMARK_BLOCK>>", baue_benchmark_block(eintrag))
        .replace("<<AI_BLOCK>>", ai_bloecke)
        .replace("<<REASONING_BLOCK>>", reasoning_block)
        .replace("<<KRITERIEN>>", html.escape(kriterien))
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
        # Der farbige Punkt stellt die Verbindung zur Akzentlinie der Karten
        # her: gleiche Farbe, gleiche Kategorie.
        tabs.append(f'<button class="tab cat-{schluessel}" data-filter="{schluessel}">'
                    f'<span class="punkt"></span>{anzeigename}'
                    f'<span class="count">{anzahl}</span></button>')

    return "\n".join(tabs)


def formatiere_treffer(p, brier_wert):
    """Zeigt Schaetzung und Brier Score einer aufgeloesten Frage.

    Fehlt die Schaetzung, steht ein Strich - dann hat dieses Modell die Frage
    nie prognostiziert, und eine 0 waere eine Behauptung.
    """
    if p is None:
        return "&ndash;"
    return f"{round(p * 100)}% <span class=\"brier\">{brier_wert:.3f}</span>"


def baue_aufgeloest_abschnitt(eintraege):
    """Baut den Abschnitt mit aufgeloesten Fragen, oder gibt leeren Text zurueck.

    Leerer Text heisst: der Abschnitt erscheint gar nicht. Solange nichts
    aufgeloest ist, waere eine Ueberschrift mit leerer Tabelle nur Rauschen -
    und sie saehe aus wie ein Fehler statt wie ein erwarteter Zustand.
    """
    if not eintraege:
        return ""

    koepfe = "".join(f"<th>{html.escape(name)}</th>" for _, name in PROGNOSTIKER)

    zeilen = []
    for eintrag in eintraege:
        zellen = "\n".join(
            AUFGELOEST_ZELLE.replace(
                "<<WERT>>", formatiere_treffer(m["model_p"], m["brier"])
            )
            for m in eintrag["modelle"]
        )
        zeilen.append(
            AUFGELOEST_ZEILE
            .replace("<<FRAGE>>", html.escape(eintrag["question"]))
            .replace("<<OUTCOME_KLASSE>>", "ja" if eintrag["outcome"] == 1 else "nein")
            .replace("<<OUTCOME>>", "Yes" if eintrag["outcome"] == 1 else "No")
            .replace("<<ZELLEN>>", zellen)
            .replace("<<BENCH>>", formatiere_treffer(eintrag["market_p"],
                                                     eintrag["market_brier"]))
            .replace("<<DATUM>>", html.escape(eintrag["measured_at"]))
        )

    return (
        AUFGELOEST_VORLAGE
        .replace("<<ANZAHL>>", str(len(eintraege)))
        .replace("<<KOEPFE>>", koepfe)
        .replace("<<ZEILEN>>", "\n".join(zeilen))
    )


def nenne_quellen(eintraege):
    """Zaehlt die tatsaechlich vertretenen Quellen auf, z. B. "Metaculus and Polymarket"."""
    # sorted() gibt eine stabile Reihenfolge, damit die Fusszeile nicht bei
    # jedem Lauf anders aussieht und unnoetige Commits erzeugt.
    namen = sorted({quellen_name(e["source"]) for e in eintraege})

    if len(namen) == 1:
        return html.escape(namen[0])
    return html.escape(", ".join(namen[:-1]) + " and " + namen[-1])


def alle_diffs(eintrag):
    """Alle vorhandenen Abweichungen einer Karte, ueber alle Modelle."""
    return [m["diff"] for m in eintrag["modelle"] if m["diff"] is not None]


def hat_prognose(eintrag):
    """True, wenn mindestens ein Modell fuer diese Frage geschaetzt hat."""
    return any(m["model_p"] is not None for m in eintrag["modelle"])


def mittlere_abweichung(eintraege):
    """Durchschnittliche absolute Abweichung in Prozentpunkten, als Text.

    Gemittelt ueber alle Modell-Benchmark-Paare, nicht ueber Karten: bei zwei
    Modellen zaehlt jede Karte doppelt, wenn beide geschaetzt haben. Gibt es
    kein einziges Paar, steht ein Strich - eine 0 waere eine Falschaussage,
    sie hiesse "Modelle und Benchmark sind sich einig".
    """
    diffs = [abs(d) for e in eintraege for d in alle_diffs(e)]
    if not diffs:
        return "&ndash;"
    return f"{round(sum(diffs) / len(diffs) * 100)} pts"


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


def baue_seite(eintraege, aufgeloest, zeitstempel):
    """Setzt Kopf, Tab-Leiste, Karten, aufgeloeste Fragen und Fusszeile zusammen."""
    sortiert = sorted(eintraege, key=sortierschluessel)
    karten = "\n".join(baue_karte(e) for e in sortiert)
    anzahl_quellen = len({e["source"] for e in sortiert})

    return (
        SEITEN_VORLAGE
        .replace("<<AUFGELOEST>>", baue_aufgeloest_abschnitt(aufgeloest))
        .replace("<<ZEITSTEMPEL>>", zeitstempel)
        .replace("<<ANZAHL_QUELLEN>>", str(anzahl_quellen))
        .replace("<<ANZAHL>>", str(len(sortiert)))
        .replace("<<DURCHSCHNITT>>", mittlere_abweichung(sortiert))
        .replace("<<TABS>>", baue_tabs(sortiert))
        .replace("<<KARTEN>>", karten)
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

    # Bauzeit in UTC. Die Action baut direkt nach dem Abruf, der Stempel steht
    # also fuer den Datenstand.
    zeitstempel = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    aufgeloest = baue_aufgeloeste_daten()
    seite = baue_seite(eintraege, aufgeloest, zeitstempel)

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
