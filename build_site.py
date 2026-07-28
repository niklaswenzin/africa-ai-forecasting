"""build_site.py

Liest markets.json und forecasts.json und schreibt daraus eine statische
Seite docs/index.html. Kein Framework, keine zusaetzlichen Bibliotheken:
nur die Standardbibliothek, das Filtern uebernimmt etwas Vanilla-JS.

Ausgangspunkt sind die Fragen aus markets.json, nicht die Prognosen. Jede
ausgewaehlte Frage bekommt eine Karte; die Prognose ist optional. Fragen ohne
Prognose zeigen nur die Marktquote, statt ganz zu fehlen.

Die Seite selbst ist auf Englisch, weil sie oeffentlich ist. Kommentare und
Funktionsnamen bleiben deutsch wie im Rest des Projekts.
"""

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Konstanten ------------------------------------------------------------

MARKETS_DATEI = "markets.json"
FORECASTS_DATEI = "forecasts.json"
AUSGABE_ORDNER = Path("docs")
AUSGABE_DATEI = AUSGABE_ORDNER / "index.html"

REPO_URL = "https://github.com/niklaswenzin/africa-ai-forecasting"

# Ab welcher Abweichung gilt Modell != Markt als nennenswert. Darunter zeigen
# wir die Differenz neutral grau an, damit Rauschen nicht wie ein Signal wirkt.
NAH_SCHWELLE = 0.05

# Anzeigenamen der Quellen. Unbekannte Quellen zeigen wir unveraendert an,
# statt sie zu verstecken.
QUELLEN_NAMEN = {
    "polymarket": "Polymarket",
    "metaculus": "Metaculus",
    "kalshi": "Kalshi",
}

# Beschriftung der Vergleichszahl. Ein Polymarket- oder Kalshi-Preis entsteht
# durch echten Geldeinsatz, der Metaculus-Wert ist der Median freiwilliger
# Community-Prognosen. Beides in eine Spalte "Market" zu schreiben, waere
# irrefuehrend, darum haengt die Beschriftung am benchmark_type.
BENCHMARK_LABEL = {
    "market_price": "Market",
    "community_forecast": "Community",
}

# Anzeigenamen und Reihenfolge der Kategorien in der Tab-Leiste. Kategorien
# ohne Fragen werden spaeter uebersprungen, damit kein leerer Tab entsteht.
KATEGORIE_NAMEN = [
    ("elections", "Elections"),
    ("security", "Security"),
    ("diplomacy", "Diplomacy"),
    ("economy", "Economy"),
    ("other", "Other"),
]


# --- Vorlagen --------------------------------------------------------------
#
# Die Vorlagen sind normale Strings mit Platzhaltern in doppelten spitzen
# Klammern. Wir setzen sie spaeter mit str.replace ein. Bewusst nicht
# .format() oder f-Strings: CSS und JavaScript enthalten geschweifte Klammern,
# die beide Verfahren als Platzhalter missverstehen wuerden.

SEITEN_VORLAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Forecasting: African Economic and Political Development</title>
<style>
:root {
  --bg: #f6f7f9;
  --card: #ffffff;
  --text: #14171a;
  --muted: #656d76;
  --line: #e1e4e8;
  --line-strong: #c9cfd6;
  --accent: #1f6feb;
  --up: #1a7f5a;
  --down: #b3341f;
  --flat: #656d76;
  --bar: #d7dce1;
  --bar-fill: #1f6feb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117;
    --card: #161b22;
    --text: #e6edf3;
    --muted: #8b949e;
    --line: #30363d;
    --line-strong: #444c56;
    --accent: #58a6ff;
    --up: #3fb950;
    --down: #f85149;
    --flat: #8b949e;
    --bar: #30363d;
    --bar-fill: #58a6ff;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2rem 1rem 3rem;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.wrap { max-width: 1140px; margin: 0 auto; }
header { margin-bottom: 1.4rem; }
h1 { font-size: 1.7rem; line-height: 1.25; margin: 0 0 .4rem; letter-spacing: -.01em; }
.sub { color: var(--muted); margin: 0 0 .5rem; max-width: 60ch; }
.stamp { color: var(--muted); font-size: .85rem; margin: 0; }

/* Tab-Leiste */
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem;
  margin: 0 0 1.4rem;
  padding-bottom: .9rem;
  border-bottom: 1px solid var(--line);
}
.tab {
  font: inherit;
  font-size: .87rem;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: .34rem .85rem;
  cursor: pointer;
}
.tab:hover { color: var(--text); }
.tab.active {
  background: var(--text);
  border-color: var(--text);
  color: var(--bg);
}
.tab .count { opacity: .65; margin-left: .3rem; font-variant-numeric: tabular-nums; }

/* Karten-Grid */
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: .9rem;
  align-items: start;
}
@media (max-width: 950px) { .grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }

.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 1rem 1.05rem 1.1rem;
  display: flex;
  flex-direction: column;
}
.card-head { display: flex; flex-wrap: wrap; gap: .35rem; margin-bottom: .7rem; }
.badge, .tag {
  font-size: .66rem;
  text-transform: uppercase;
  letter-spacing: .07em;
  font-weight: 600;
  color: var(--muted);
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: .13rem .5rem;
}
.tag { border-style: dashed; }
.question { font-weight: 600; margin: 0 0 .95rem; font-size: .97rem; }

/* Benchmark mit Balken */
.bench-row { display: flex; align-items: baseline; justify-content: space-between; }
.bench-label, .ai-label {
  font-size: .7rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted);
}
.bench-value { font-size: 1.65rem; font-weight: 650; font-variant-numeric: tabular-nums; }
.bar {
  height: 5px;
  background: var(--bar);
  border-radius: 999px;
  overflow: hidden;
  margin: .35rem 0 .9rem;
}
.bar-fill { height: 100%; background: var(--bar-fill); border-radius: 999px; }

/* AI-Block */
.ai { border-top: 1px solid var(--line); padding-top: .75rem; }
.ai-row { display: flex; align-items: baseline; gap: .55rem; }
.ai-value { font-size: 1.2rem; font-weight: 650; font-variant-numeric: tabular-nums; }
.diff { font-size: .87rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--flat); }
.meta { margin: .45rem 0 0; font-size: .78rem; color: var(--muted); }
.pending {
  border-top: 1px solid var(--line);
  padding-top: .75rem;
  margin: 0;
  font-size: .8rem;
  color: var(--muted);
  font-style: italic;
}

details { margin-top: .8rem; border-top: 1px solid var(--line); padding-top: .7rem; }
summary { cursor: pointer; font-size: .82rem; color: var(--accent); }
details p { margin: .6rem 0 0; font-size: .88rem; }
details .criteria {
  margin: .6rem 0 0;
  font-size: .8rem;
  color: var(--muted);
  white-space: pre-wrap;
}

footer {
  margin-top: 2.5rem;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
  font-size: .85rem;
  color: var(--muted);
  max-width: 75ch;
}
footer a { color: var(--accent); }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>AI Forecasting: African Economic and Political Development</h1>
  <p class="sub">Claude&rsquo;s probability estimates next to prediction-market prices
  and community forecasts. The model never sees the benchmark.</p>
  <p class="stamp">Last updated <<ZEITSTEMPEL>> &middot; <<ANZAHL>> open questions
  &middot; <<ANZAHL_AI>> with an AI forecast</p>
</header>

<nav class="tabs"><<TABS>></nav>

<div class="grid">
<<KARTEN>>
</div>

<footer>
<p>The model never sees the benchmark: <code>forecast.py</code> passes only the
question and its resolution criteria, so the estimate is independent rather than
a restatement of the market. Forecasts are produced with the Claude API
(<code>claude-sonnet-4-6</code>) and may use web search for recent events.</p>
<p>Questions and benchmarks on this page come from <<QUELLEN_LISTE>>. Market prices
reflect real money at stake; community forecasts are the median of volunteer
predictions and are labelled separately. Source and method:
<a href="<<REPO_URL>>"><<REPO_URL>></a></p>
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

KARTEN_VORLAGE = """<article class="card" data-category="<<KATEGORIE>>">
  <div class="card-head">
    <span class="badge"><<QUELLE>></span>
    <span class="tag"><<LAND>></span>
  </div>
  <p class="question"><<FRAGE>></p>
  <div class="bench-row">
    <span class="bench-label"><<BENCHMARK_LABEL>></span>
    <span class="bench-value"><<MARKT_P>></span>
  </div>
  <div class="bar"><div class="bar-fill" style="width: <<BALKEN>>%"></div></div>
<<AI_BLOCK>>
  <details>
    <summary>Details</summary>
<<REASONING_BLOCK>>
    <p class="criteria"><<KRITERIEN>></p>
  </details>
</article>"""

AI_VORLAGE = """  <div class="ai">
    <div class="ai-row">
      <span class="ai-label">Claude</span>
      <span class="ai-value"><<MODELL_P>></span>
      <span class="diff <<DIFF_KLASSE>>"><<DIFF>></span>
    </div>
    <p class="meta">Confidence: <<CONFIDENCE>> &middot; <<SUCHE>></p>
  </div>"""

OHNE_AI_VORLAGE = """  <p class="pending">No AI forecast yet</p>"""


# --- Daten laden -----------------------------------------------------------

def lade_json(pfad):
    """Liest eine JSON-Datei (UTF-8). Fehlt sie, brechen wir klar ab.

    Gleiche Fehlerbehandlung wie in evaluate.py: lieber eine verstaendliche
    Meldung als ein Traceback.
    """
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

    Ausgangspunkt sind die Fragen, nicht die Prognosen: eine Frage ohne
    Prognose soll ihre Marktquote zeigen und nicht verschwinden. Das tritt
    auf, wenn ein Forecast-Lauf abgebrochen ist oder spaeter, wenn bewusst nur
    ein Teil der Fragen prognostiziert wird.
    """
    nach_id = {prognose["id"]: prognose for prognose in forecasts}

    eintraege = []
    for markt in markets:
        prognose = nach_id.get(markt["id"])
        market_p = markt.get("market_p")

        if prognose is None:
            model_p = None
            diff = None
        else:
            model_p = prognose["probability"]
            diff = None if market_p is None else round(model_p - market_p, 4)

        eintraege.append({
            "question": markt["question"],
            "source": markt.get("source", "unknown"),
            "benchmark_type": markt.get("benchmark_type", "market_price"),
            "category": markt.get("category", "other"),
            "country": markt.get("country", ""),
            "market_p": market_p,
            "model_p": model_p,
            "diff": diff,
            "confidence": prognose["confidence"] if prognose else "",
            "reasoning": prognose["reasoning"] if prognose else "",
            "searched": prognose.get("searched", False) if prognose else False,
            "num_searches": prognose.get("num_searches", 0) if prognose else 0,
            "criteria": markt.get("description", ""),
        })

    return eintraege


# --- Formatierung ----------------------------------------------------------

def formatiere_prozent(p):
    """Macht aus 0.72 die Anzeige "72%". Fehlt der Wert, kommt ein Strich."""
    if p is None:
        return "&ndash;"
    return f"{round(p * 100)}%"


def balken_breite(p):
    """Breite des Wahrscheinlichkeitsbalkens in Prozent, als Text fuer CSS.

    Fehlt die Quote, bleibt der Balken leer (0), statt die Karte kaputtzumachen.
    """
    if p is None:
        return "0"
    return str(round(p * 100))


def formatiere_diff(diff):
    """Formatiert die Differenz mit Pfeil und Vorzeichen, z. B. "&#9650; 46 pts".

    Zwei Sonderfaelle: rundet die Differenz auf 0 Punkte, waere "+0 pts"
    irrefuehrend (der Wert ist nicht exakt null), darum "<1 pt". Und bei
    genau einem Punkt heisst es "pt", nicht "pts".
    """
    if diff is None:
        return "&ndash;"

    punkte = round(diff * 100)
    if punkte == 0:
        return "&#9679; &lt;1 pt"

    pfeil = "&#9650;" if punkte > 0 else "&#9660;"
    einheit = "pt" if abs(punkte) == 1 else "pts"
    return f"{pfeil} {abs(punkte)} {einheit}"


def klasse_fuer_diff(diff):
    """Waehlt die CSS-Klasse (Farbe) fuer die Differenz.

    Abweichungen unterhalb von NAH_SCHWELLE zeigen wir neutral grau, damit
    kleine Unterschiede optisch nicht wie eine echte Gegenposition wirken.
    """
    if diff is None or abs(diff) < NAH_SCHWELLE:
        return "flat"
    return "up" if diff > 0 else "down"


def quellen_name(quelle):
    """Anzeigename einer Quelle, z. B. "polymarket" -> "Polymarket"."""
    return QUELLEN_NAMEN.get(quelle, quelle)


def benchmark_label(benchmark_type):
    """Beschriftung der Vergleichszahl, abhaengig von der Art des Benchmarks."""
    return BENCHMARK_LABEL.get(benchmark_type, "Benchmark")


def beschreibe_suche(eintrag):
    """Formuliert den Hinweis, ob und wie oft das Modell gesucht hat."""
    if not eintrag["searched"]:
        return "no web search"
    anzahl = eintrag["num_searches"]
    return f"{anzahl} web search{'es' if anzahl != 1 else ''}"


# --- HTML bauen ------------------------------------------------------------

def baue_ai_block(eintrag):
    """Baut den Claude-Teil der Karte, oder den Hinweis, dass er noch fehlt."""
    if eintrag["model_p"] is None:
        return OHNE_AI_VORLAGE

    return (
        AI_VORLAGE
        .replace("<<MODELL_P>>", formatiere_prozent(eintrag["model_p"]))
        .replace("<<DIFF_KLASSE>>", klasse_fuer_diff(eintrag["diff"]))
        .replace("<<DIFF>>", formatiere_diff(eintrag["diff"]))
        .replace("<<CONFIDENCE>>", html.escape(eintrag["confidence"]))
        .replace("<<SUCHE>>", beschreibe_suche(eintrag))
    )


def baue_karte(eintrag):
    """Baut das HTML fuer eine einzelne Frage-Karte.

    Alle Texte laufen durch html.escape. Frage, Begruendung und Kriterien
    stammen aus der Markt-API bzw. vom Modell; ein "&" oder "<" darin wuerde
    die Seite sonst zerlegen.
    """
    kriterien = eintrag["criteria"].strip() or "No resolution criteria provided."

    if eintrag["reasoning"]:
        reasoning_block = f"    <p>{html.escape(eintrag['reasoning'])}</p>"
    else:
        reasoning_block = ""

    return (
        KARTEN_VORLAGE
        .replace("<<KATEGORIE>>", html.escape(eintrag["category"]))
        .replace("<<QUELLE>>", html.escape(quellen_name(eintrag["source"])))
        .replace("<<LAND>>", html.escape(eintrag["country"] or "Africa"))
        .replace("<<FRAGE>>", html.escape(eintrag["question"]))
        .replace("<<BENCHMARK_LABEL>>", benchmark_label(eintrag["benchmark_type"]))
        .replace("<<MARKT_P>>", formatiere_prozent(eintrag["market_p"]))
        .replace("<<BALKEN>>", balken_breite(eintrag["market_p"]))
        .replace("<<AI_BLOCK>>", baue_ai_block(eintrag))
        .replace("<<REASONING_BLOCK>>", reasoning_block)
        .replace("<<KRITERIEN>>", html.escape(kriterien))
    )


def baue_tabs(eintraege):
    """Baut die Tab-Leiste aus den tatsaechlich vorhandenen Kategorien.

    Kategorien ohne Fragen bekommen keinen Tab. Ein Tab, der auf eine leere
    Liste filtert, sieht nach einem Fehler aus - und welche Kategorien belegt
    sind, aendert sich mit den Quellen und der Nachrichtenlage.
    """
    tabs = [f'<button class="tab active" data-filter="all">All'
            f'<span class="count">{len(eintraege)}</span></button>']

    for schluessel, anzeigename in KATEGORIE_NAMEN:
        anzahl = sum(1 for e in eintraege if e["category"] == schluessel)
        if anzahl == 0:
            continue
        tabs.append(f'<button class="tab" data-filter="{schluessel}">{anzeigename}'
                    f'<span class="count">{anzahl}</span></button>')

    return "\n".join(tabs)


def nenne_quellen(eintraege):
    """Zaehlt die tatsaechlich vertretenen Quellen auf, z. B. "Polymarket and Kalshi".

    Bewusst aus den Daten abgeleitet und nicht fest hingeschrieben: solange
    Metaculus und Kalshi keine Fragen liefern, sollen sie in der Fusszeile auch
    nicht als Quelle behauptet werden.
    """
    # sorted() gibt eine stabile Reihenfolge, damit die Fusszeile nicht bei
    # jedem Lauf anders aussieht und unnoetige Commits erzeugt.
    namen = sorted({quellen_name(e["source"]) for e in eintraege})

    if len(namen) == 1:
        return html.escape(namen[0])
    return html.escape(", ".join(namen[:-1]) + " and " + namen[-1])


def sortierschluessel(eintrag):
    """Sortierung der Karten: erst mit Prognose nach groesster Abweichung.

    Karten mit Prognose stehen vorn, weil nur dort ein Vergleich sichtbar ist -
    und innerhalb davon zuerst die groesste Abweichung, denn das ist der
    interessante Teil. Karten ohne Prognose folgen danach, nach Marktquote
    absteigend. Sonst stuenden unfertige Karten oben.
    """
    hat_prognose = eintrag["diff"] is not None
    if hat_prognose:
        return (0, -abs(eintrag["diff"]))
    return (1, -(eintrag["market_p"] or 0))


def baue_seite(eintraege, zeitstempel):
    """Setzt Kopf, Tab-Leiste, alle Karten und Fusszeile zur fertigen Seite zusammen."""
    sortiert = sorted(eintraege, key=sortierschluessel)
    karten = "\n".join(baue_karte(e) for e in sortiert)
    mit_prognose = sum(1 for e in sortiert if e["model_p"] is not None)

    return (
        SEITEN_VORLAGE
        .replace("<<ZEITSTEMPEL>>", zeitstempel)
        .replace("<<ANZAHL_AI>>", str(mit_prognose))
        .replace("<<ANZAHL>>", str(len(sortiert)))
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
    # also fuer den Datenstand. Weder markets.json noch forecasts.json bringen
    # einen eigenen Zeitstempel mit.
    zeitstempel = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    seite = baue_seite(eintraege, zeitstempel)

    AUSGABE_ORDNER.mkdir(exist_ok=True)
    with open(AUSGABE_DATEI, "w", encoding="utf-8") as datei:
        datei.write(seite)

    mit_prognose = sum(1 for e in eintraege if e["model_p"] is not None)
    print(f"{len(eintraege)} Karten nach {AUSGABE_DATEI} geschrieben "
          f"({mit_prognose} davon mit Prognose).")


if __name__ == "__main__":
    main()
