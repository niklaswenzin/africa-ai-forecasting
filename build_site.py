"""build_site.py

Liest markets.json und forecasts.json, verbindet beide ueber die id und
schreibt daraus eine statische Seite docs/index.html. Kein Framework, keine
zusaetzlichen Bibliotheken: nur die Standardbibliothek.

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


# --- Vorlagen --------------------------------------------------------------
#
# Die Vorlagen sind normale Strings mit Platzhaltern in doppelten spitzen
# Klammern. Wir setzen sie spaeter mit str.replace ein. Bewusst nicht
# .format() oder f-Strings: der CSS-Block enthaelt geschweifte Klammern, die
# beide Verfahren als Platzhalter missverstehen wuerden.

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
  --accent: #1f6feb;
  --up: #1a7f5a;
  --down: #b3341f;
  --flat: #656d76;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117;
    --card: #161b22;
    --text: #e6edf3;
    --muted: #8b949e;
    --line: #30363d;
    --accent: #58a6ff;
    --up: #3fb950;
    --down: #f85149;
    --flat: #8b949e;
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
.wrap { max-width: 820px; margin: 0 auto; }
header { margin-bottom: 2rem; }
h1 { font-size: 1.6rem; line-height: 1.25; margin: 0 0 .4rem; letter-spacing: -.01em; }
.sub { color: var(--muted); margin: 0 0 .6rem; }
.stamp { color: var(--muted); font-size: .85rem; margin: 0; }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 1.1rem 1.2rem;
  margin-bottom: .9rem;
}
.badge {
  display: inline-block;
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .07em;
  font-weight: 600;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: .15rem .55rem;
  margin-bottom: .6rem;
}
.question { font-weight: 600; margin: 0 0 1rem; }
.nums { display: flex; flex-wrap: wrap; gap: 1.5rem; align-items: baseline; }
.num { min-width: 5.5rem; }
.num .label {
  display: block;
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted);
  margin-bottom: .15rem;
}
.num .value { font-size: 1.5rem; font-weight: 650; font-variant-numeric: tabular-nums; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--flat); }
.meta { margin-top: .9rem; font-size: .82rem; color: var(--muted); }
details { margin-top: .9rem; border-top: 1px solid var(--line); padding-top: .8rem; }
summary { cursor: pointer; font-size: .88rem; color: var(--accent); }
details p { margin: .7rem 0 0; }
details .criteria {
  margin: .7rem 0 0;
  font-size: .85rem;
  color: var(--muted);
  white-space: pre-wrap;
}
footer {
  margin-top: 2.5rem;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
  font-size: .85rem;
  color: var(--muted);
}
footer a { color: var(--accent); }
@media (max-width: 480px) {
  .nums { gap: 1.1rem; }
  .num .value { font-size: 1.25rem; }
}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>AI Forecasting: African Economic and Political Development</h1>
  <p class="sub">Claude&rsquo;s probability estimates next to prediction-market prices
  and community forecasts.</p>
  <p class="stamp">Last updated <<ZEITSTEMPEL>> &middot; <<ANZAHL>> open questions</p>
</header>

<<KARTEN>>

<footer>
<p>The model never sees the market price: <code>forecast.py</code> passes only the
question and its resolution criteria, so the estimate is independent rather than
a restatement of the market. Forecasts are produced with the Claude API
(<code>claude-sonnet-4-6</code>) and may use web search for recent events.</p>
<p>Questions and benchmarks on this page come from <<QUELLEN_LISTE>>. Market prices
reflect real money at stake; community forecasts are the median of volunteer
predictions and are labelled separately. Source and method:
<a href="<<REPO_URL>>"><<REPO_URL>></a></p>
</footer>
</div>
</body>
</html>
"""

KARTEN_VORLAGE = """<article class="card">
  <span class="badge"><<QUELLE>></span>
  <p class="question"><<FRAGE>></p>
  <div class="nums">
    <div class="num">
      <span class="label"><<BENCHMARK_LABEL>></span>
      <span class="value"><<MARKT_P>></span>
    </div>
    <div class="num">
      <span class="label">Claude</span>
      <span class="value"><<MODELL_P>></span>
    </div>
    <div class="num">
      <span class="label">Difference</span>
      <span class="value <<DIFF_KLASSE>>"><<DIFF>></span>
    </div>
  </div>
  <p class="meta">Confidence: <<CONFIDENCE>> &middot; <<SUCHE>></p>
  <details>
    <summary>Reasoning and resolution criteria</summary>
    <p><<REASONING>></p>
    <p class="criteria"><<KRITERIEN>></p>
  </details>
</article>"""


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
    """Verbindet Prognosen und Marktdaten ueber die id.

    Die Zuordnung laeuft ueber die id und nicht ueber die Reihenfolge, weil
    forecast.py Fragen ueberspringen kann, wenn keine gueltige Antwort kam.
    Fragen ohne Prognose tauchen auf der Seite gar nicht erst auf.
    """
    nach_id = {markt["id"]: markt for markt in markets}

    eintraege = []
    for prognose in forecasts:
        markt = nach_id.get(prognose["id"])
        if markt is None:
            print(
                f"Hinweis: keine Marktdaten fuer id {prognose['id']}, "
                f"Frage wird uebersprungen.",
                file=sys.stderr,
            )
            continue

        model_p = prognose["probability"]
        market_p = markt.get("market_p")
        diff = None if market_p is None else round(model_p - market_p, 4)

        eintraege.append({
            "question": prognose["question"],
            "source": markt.get("source", "unknown"),
            "benchmark_type": markt.get("benchmark_type", "market_price"),
            "model_p": model_p,
            "market_p": market_p,
            "diff": diff,
            "confidence": prognose["confidence"],
            "reasoning": prognose["reasoning"],
            "searched": prognose.get("searched", False),
            "num_searches": prognose.get("num_searches", 0),
            "criteria": markt.get("description", ""),
        })

    return eintraege


# --- Formatierung ----------------------------------------------------------

def formatiere_prozent(p):
    """Macht aus 0.72 die Anzeige "72%". Fehlt der Wert, kommt ein Strich."""
    if p is None:
        return "&ndash;"
    return f"{round(p * 100)}%"


def formatiere_diff(diff):
    """Formatiert die Differenz mit Vorzeichen, z. B. "+46 pts".

    Zwei Sonderfaelle: rundet die Differenz auf 0 Punkte, waere "+0 pts"
    irrefuehrend (der Wert ist nicht exakt null), darum "<1 pt". Und bei
    genau einem Punkt heisst es "pt", nicht "pts".
    """
    if diff is None:
        return "&ndash;"

    punkte = round(diff * 100)
    if punkte == 0:
        return "&lt;1 pt"

    einheit = "pt" if abs(punkte) == 1 else "pts"
    return f"{punkte:+d} {einheit}"


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

def baue_karte(eintrag):
    """Baut das HTML fuer eine einzelne Frage-Karte.

    Alle Texte laufen durch html.escape. Frage, Begruendung und Kriterien
    stammen aus der Polymarket-API bzw. vom Modell; ein "&" oder "<" darin
    wuerde die Seite sonst zerlegen.
    """
    kriterien = eintrag["criteria"].strip() or "No resolution criteria provided."

    return (
        KARTEN_VORLAGE
        .replace("<<QUELLE>>", html.escape(quellen_name(eintrag["source"])))
        .replace("<<BENCHMARK_LABEL>>", benchmark_label(eintrag["benchmark_type"]))
        .replace("<<FRAGE>>", html.escape(eintrag["question"]))
        .replace("<<MARKT_P>>", formatiere_prozent(eintrag["market_p"]))
        .replace("<<MODELL_P>>", formatiere_prozent(eintrag["model_p"]))
        .replace("<<DIFF_KLASSE>>", klasse_fuer_diff(eintrag["diff"]))
        .replace("<<DIFF>>", formatiere_diff(eintrag["diff"]))
        .replace("<<CONFIDENCE>>", html.escape(eintrag["confidence"]))
        .replace("<<SUCHE>>", beschreibe_suche(eintrag))
        .replace("<<REASONING>>", html.escape(eintrag["reasoning"]))
        .replace("<<KRITERIEN>>", html.escape(kriterien))
    )


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


def baue_seite(eintraege, zeitstempel):
    """Setzt Kopf, alle Karten und Fusszeile zur fertigen Seite zusammen.

    Die Karten werden absteigend nach dem Betrag der Differenz sortiert: die
    Fragen, bei denen Modell und Markt am weitesten auseinanderliegen, stehen
    oben, denn das ist der interessante Teil.
    """
    sortiert = sorted(
        eintraege,
        key=lambda e: abs(e["diff"]) if e["diff"] is not None else -1,
        reverse=True,
    )

    karten = "\n".join(baue_karte(e) for e in sortiert)

    return (
        SEITEN_VORLAGE
        .replace("<<ZEITSTEMPEL>>", zeitstempel)
        .replace("<<ANZAHL>>", str(len(sortiert)))
        .replace("<<KARTEN>>", karten)
        .replace("<<QUELLEN_LISTE>>", nenne_quellen(eintraege))
        .replace("<<REPO_URL>>", REPO_URL)
    )


# --- Hauptablauf -----------------------------------------------------------

def main():
    markets = lade_json(MARKETS_DATEI)
    forecasts = lade_json(FORECASTS_DATEI)

    eintraege = baue_karten_daten(markets, forecasts)
    if not eintraege:
        print(
            "Fehler: keine Frage hat Marktdaten UND eine Prognose. "
            "Seite wird nicht geschrieben.",
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

    print(f"{len(eintraege)} Karten nach {AUSGABE_DATEI} geschrieben.")


if __name__ == "__main__":
    main()
