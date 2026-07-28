# AI Forecasting: African Economic and Political Development

Claude produces probability estimates for open questions about African politics and
economics, and the results are published next to the corresponding prediction-market
prices. The model never sees the market price, so the two numbers are independent.

**Live dashboard: https://niklaswenzin.github.io/africa-ai-forecasting/**

The site rebuilds itself from live data, so the numbers below will differ from
whatever you see today.

## What it does

Four scripts, run in order:

| Script | Does | Writes |
|---|---|---|
| `fetch_markets.py` | Loads open questions from every configured source, keeps those with an African subject, drops sports questions, takes at most one question per country | `markets.json` |
| `forecast.py` | One Claude API call per question, optionally with web search, returns validated JSON | `forecasts.json` |
| `evaluate.py` | Joins both files by id and compares model against benchmark | `results.csv` |
| `build_site.py` | Renders the static dashboard | `docs/index.html` |

```bash
python fetch_markets.py && python forecast.py && python evaluate.py && python build_site.py
```

## Quickstart

Python 3.10 or newer.

```bash
pip install requests anthropic
```

The Claude API key is read from the `ANTHROPIC_API_KEY` environment variable, or from
a local `.env` file containing `ANTHROPIC_API_KEY=...`. The `.env` file is excluded by
`.gitignore` and must never be committed.

```bash
export ANTHROPIC_API_KEY=your-key-here
python fetch_markets.py
```

Only `fetch_markets.py` and `build_site.py` run without a key; `forecast.py` needs one.
A full run of five questions costs a few cents.

## Sources

Each source lives in its own `source_*.py` and exposes a single `lade_fragen()`
function returning entries in a shared format. Adding a source means writing one file
and listing it in `QUELLEN` — the Africa filter, the sports filter and the
one-question-per-country rule then apply to it automatically.

| Source | Status | Benchmark |
|---|---|---|
| Polymarket | live, via the public Gamma API | `market_price` |
| Metaculus | prepared, not yet connected | `community_forecast` |
| Kalshi | prepared, not yet connected | `market_price` |

The two benchmark types are deliberately kept apart. A Polymarket or Kalshi price
reflects real money at stake. The Metaculus number is the median of volunteer
forecasts with nothing at risk. They are not the same kind of evidence, so the
dashboard labels them differently ("Market" vs "Community") and `results.csv` carries
`benchmark_type` as its own column.

The two unconnected sources return an empty list rather than a guessed endpoint. What
still has to be verified in their official documentation is listed at the top of each
placeholder file.

## Method

The market price is never passed to the model. `forecast.py` sends only the question
text and its resolution criteria; the price is used exclusively by `evaluate.py`
afterwards. Without that separation the model tends to restate the market instead of
producing an independent estimate, and the comparison becomes meaningless.

Resolution criteria are included in the prompt on purpose. Many of these questions turn
on a formal condition — a signed agreement rather than a declaration of intent, an
official electoral commission result rather than a press report — and the model gets
those wrong when it only sees the headline question.

The system prompt forces a single JSON object with `probability` (0 to 1), `reasoning`
(max three sentences) and `confidence` (`low`, `medium`, `high`). Invalid JSON is
requested exactly once more, then the question is skipped.

## Limitations

These are real and worth stating plainly.

**Forecasts are not stable across runs.** The same question, with the same resolution
criteria and an essentially unchanged news situation, can produce very different
estimates. "Will Somaliland join the Abraham Accords before 2027?" came out at 0.28,
then 0.72, then 0.62 across three consecutive runs, against a market price of about
0.245. The disagreement with the market is the most visible claim the dashboard makes,
and at present it is partly an artefact of sampling variance rather than a considered
position. Reducing temperature, or sampling each question several times and averaging,
would address this; neither is implemented yet.

**No accuracy score yet.** Every question currently tracked is still open, so there is
no Brier score and no calibration measurement — only the difference between model and
market, which says nothing about who is right. Scoring properly requires resolved
questions, and to be fair it needs a market price snapshot taken well before
resolution: near the end a market converges to 0 or 1 and beats any forecaster
trivially.

**African questions are scarce.** In a recent run the pipeline saw 11,616 unique open
Polymarket markets and found 48 with an African subject. The real total is higher and
cannot be enumerated exactly: the Gamma API caps the offset at 2,000 per sort order, so
the code unions several sort orders instead of paging through everything. Either way,
the African subset is small and clusters around a handful of elections, which is why
the selection is capped at one question per country.

**Topic filtering is keyword-based.** The Gamma API returns no category or tags, so
African relevance is detected from the question text against a country and leader
keyword list, and sports questions are excluded by a negative list (`cricket`, `cup`,
`" vs "`, `t20` and so on). Matching is on word boundaries, not substrings, because
`niger` is contained in `Nigeria` and `mali` in `Somalia`. The generic term `africa` is
deliberately absent, since it matches "North Africa", and so is `chad`, which matched
people named Chad rather than the country. This is a pragmatic filter, not a classifier.

**Server-side sorting is unreliable.** Volume ordering from the API is inconsistent
across pages, so the code sorts client-side after collecting results.

**The selection changes between runs.** Questions are chosen from live data by volume
and by how far the price is from the extremes, so a run on a different day will not
necessarily track the same five questions.

## Repository

```
fetch_markets.py       orchestrates the sources, filters and selects
source_polymarket.py   Polymarket via the Gamma API
source_metaculus.py    placeholder, returns []
source_kalshi.py       placeholder, returns []
forecast.py            Claude API calls, JSON validation
evaluate.py            comparison table
build_site.py          static site generator
docs/index.html        the generated dashboard
```

`markets.json`, `forecasts.json` and `results.csv` are committed so that each run's
input and output stay reproducible.
