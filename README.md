# AI Forecasting: African Economic and Political Development

Two language models — Claude and GPT — estimate the probability of open questions
about African politics and economics. Their estimates are published next to the
corresponding prediction-market price. Neither model ever sees that price, so the
two numbers are independent.

**Live dashboard: https://niklaswenzin.github.io/africa-ai-forecasting/**

The site is rebuilt from live data, so the numbers below will differ from
whatever you see today.

## What it does

Three scripts, run in order:

| Script | Does | Writes |
|---|---|---|
| `fetch_markets.py` | Loads open questions from every configured source, keeps those with an African subject, drops sports questions, takes at most one question per country | `markets.json` |
| `forecast.py` | One API call per question and per model, both with web search, returns validated JSON | `forecasts.json` |
| `build_site.py` | Renders the static dashboard | `docs/index.html` |

```bash
python fetch_markets.py && python forecast.py && python build_site.py
```

`snapshot.py` is optional and runs after `forecast.py`. It appends the current
state to `data/history/` so that a later evaluation can score each forecast
against the information available when it was made. Nothing on the site depends
on it.

## Quickstart

Python 3.10 or newer.

```bash
pip install requests anthropic
```

API keys are read from environment variables, or from a local `.env` file
excluded by `.gitignore`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and
`METACULUS_API_TOKEN`. They must never be committed.

Only `fetch_markets.py` and `build_site.py` run without keys; `forecast.py`
needs both model keys. A full run of ten questions costs one to two Swiss francs.

## Sources

Each source lives in its own `source_*.py` and exposes a single `lade_fragen()`
function returning entries in a shared format. Adding a source means writing one
file and listing it in `QUELLEN` — the Africa filter, the sports filter and the
one-question-per-country rule then apply to it automatically.

| Source | Benchmark | Status |
|---|---|---|
| Polymarket | `market_price`, via the public Gamma API | live, with prices |
| Metaculus | `community_forecast` | live, but the median is not readable |

The two benchmark types are deliberately kept apart. A Polymarket price reflects
real money at stake; a Metaculus number is the median of volunteer forecasts with
nothing at risk. They are not the same kind of evidence, so the dashboard labels
them differently ("Market" vs "Community").

## Method

The benchmark is never passed to the models. `forecast.py` sends only the question
text and its resolution criteria. Without that separation a model tends to restate
the market instead of producing an independent estimate, and the comparison becomes
meaningless. For the same reason, prediction-market domains are blocked in both
models' web-search tools.

Resolution criteria are included in the prompt on purpose. Many of these questions
turn on a formal condition — a signed agreement rather than a declaration of
intent, an official electoral commission result rather than a press report — and
models get them wrong when they only see the headline question.

Both models receive the identical prompt and the identical web-search tool. The
system prompt forces a single JSON object with `probability` (0 to 1), `reasoning`
(max three sentences) and `confidence`. Invalid JSON is requested exactly once
more.

`pruefung.py` cross-checks extreme estimates (below 2% or above 98%) against the
model's own reasoning. A forecast of 0.5% justified with "this is very likely"
is a direction error, not a confident position; the question is asked once more,
and if the contradiction survives, the card carries a visible warning.

## Limitations

These are real and worth stating plainly.

**Forecasts are not stable across runs.** The same question, with the same
resolution criteria and an essentially unchanged news situation, can produce very
different estimates. Measured across consecutive runs, Claude moved by 10.7
percentage points on average and by 37 at most. Neither model accepts a
temperature parameter, so sampling cannot be constrained; the larger cause is
that server-side web search returns different results each time, which takes
effect before sampling does. Averaging several runs per question would address
this and is not implemented.

**There is no accuracy score.** Every question shown is still open, so nothing has
been scored yet. `snapshot.py` records each run to `data/history/`, which is the
part that has to be right *before* the first question resolves: any later scoring
must compare model and benchmark from the **same** snapshot. Scoring a market
against its price shortly before resolution would make it unbeatable, because a
market converges to 0 or 1 once the outcome is obvious. That is a measurement
artefact, not a result.

**Metaculus medians are not readable.** The community median is `null` for every
question under this account's access tier, as is `resolution` for resolved
questions. Those questions still appear — a model can forecast them — but with no
benchmark to compare against. That is why only about half the cards show a
benchmark number.

**Most African markets on Polymarket are past their resolution date.** Of 46
questions with an African subject, 36 had a resolution date in the past while
still showing `closed: false` — the event happened, the oracle never settled the
market. Ethiopia's June 2026 election is the clearest case: Abiy Ahmed won, and
59 days later the market was still open. Both models "forecast" that question at
0.99 and 0.80 — they were reading the result, not predicting it. Such questions
are excluded. A question whose event has already occurred but whose resolution
date still lies ahead is not caught; the date is the only signal the sources give.

**Minimum liquidity.** A benchmark nobody trades is not a benchmark. One Zambian
market showed a price of 0.4% on 1,141 USD of total volume; a single small trade
moves a price like that. Questions whose benchmark falls below 5,000 USD of volume
are excluded — a threshold read off the actual distribution, where the usable
range starts around 6,500 and an isolated cluster sits between 71 and 4,200. The
rule applies only where a benchmark exists.

**The two models are not price-matched.** Claude Sonnet 5 costs 3 USD per million
input tokens and 15 per million output; the GPT model costs 1 and 6. The
comparison therefore measures a price class as well as a model, and a difference
in quality cannot be separated from a difference in budget.

**African questions are scarce, and that is the binding constraint.** The
pipeline enumerates every open Polymarket market — over 40,000 — and finds 60
with an African subject. Of those, 36 are past their resolution date and 21 of
the remainder are candidate variants of one election in Guinea-Bissau. Nine
survive as usable, distinct questions.

That number is not limited by the code. An earlier version saw only 11,616
markets, because `/markets` caps the offset at 2,000 and the code unioned
several sort orders to approximate a full scan. Switching to `/markets/keyset`
removed the cap and made the list complete rather than sampled — and raised the
African count from 48 to 60. Tripling the markets scanned added four usable
questions. Polymarket simply lists little about Africa.

**Topic filtering is keyword-based.** The Gamma API returns no category or tags,
so African relevance is detected from the question text against a country and
leader keyword list, and sports questions are excluded by a negative list. Matching
is on word boundaries, not substrings, because `niger` is contained in `Nigeria`
and `mali` in `Somalia`. The generic term `africa` is deliberately absent, since it
matches "North Africa", and so is `chad`, which matched people named Chad rather
than the country. This is a pragmatic filter, not a classifier.

**The selection changes between runs.** Questions are chosen from live data, so a
run on a different day will not necessarily track the same questions.

## Repository

```
fetch_markets.py       orchestrates the sources, filters and selects
source_polymarket.py   Polymarket via the Gamma API
source_metaculus.py    Metaculus via the posts API
forecast.py            Claude call, JSON validation, plausibility retry
forecaster_openai.py   the same task sent to the OpenAI Responses API
pruefung.py            cross-checks extreme values against their reasoning
snapshot.py            optional, appends the run to data/history/
build_site.py          static site generator
docs/index.html        the generated dashboard
```

`markets.json` and `forecasts.json` are committed so that each run's input and
output stay reproducible.
