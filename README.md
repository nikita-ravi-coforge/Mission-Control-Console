# Mission Control: Go/No-Go Launch Console

[![CI](https://github.com/nikita-ravi-coforge/Mission-Control-Console/actions/workflows/ci.yml/badge.svg)](https://github.com/nikita-ravi-coforge/Mission-Control-Console/actions/workflows/ci.yml)

Engineers at the consoles file free-text anomaly reports. A pipeline sorts each
one, checks its readings against the launch limits, and drafts a short briefing.
The Flight Director reads the briefing and approves it.

Three rules shape the whole app:

- **Models do the fuzzy work.** Sorting, the three note checks, drafting, and reviewing.
- **Code does the safety work.** Input validation, the go/no-go verdict, the brief-by time, and cost.
- **A person has the final say.** Only the approve button can approve a briefing.

## Prerequisite

[uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the
right Python and every dependency the first time you run a command.

## Start the app

```
uv run python -m app
```

Then open http://localhost:8000.

With no API key the app starts in **FAKE MODEL MODE** (yellow banner): model
replies are scripted, so everything works with no key. Reports are saved in
`data/mission_control.db` and are still there after a restart.

### Using real Claude models

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. The same start command
then uses Claude, with two models behind one interface:

| Tier | Used for | Default model | Setting |
|---|---|---|---|
| fast | sorting, the three checks | `claude-haiku-5-5` | `MODEL_FAST` |
| strong | drafting and reviewing the briefing | `claude-sonnet-5-5` | `MODEL_STRONG` |

Any model priced in `app/pricing.py` can be used for either tier, for example
`MODEL_STRONG=claude-fable-5-2`. The app refuses to start with a model that has no
price, so a report's cost is never silently wrong. `.env` is git-ignored; never
commit a key.

## Run the tests

```
uv run pytest
```

The tests need no network and no API key. Every model call goes through one
interface (`app/llm/base.py`) and the tests use the fake (`app/llm/fake.py`).
Network access is switched off during tests (`--disable-socket` in
`pyproject.toml`), so a real call would fail the run.

## What happens to a report

| # | Step | Done by | Where |
|---|---|---|---|
| 1 | Validate the form input | code | `app/schemas.py`, `app/api.py` |
| 2 | Check readings against launch limits, set the verdict | code | `app/limits.py` |
| 3 | Sort by subsystem and severity | model, validated in code | `app/pipeline/classify.py` |
| 4 | Scan the note for instruction-like text | code | `app/pipeline/checks.py` |
| 5 | Three checks at the same time: hidden instructions, missing details, panic | model ×3 | `app/pipeline/checks.py` |
| 6 | Brief-by time: 5 / 15 / 30 min; any violation counts as high | code | `app/brief_by.py` |
| 7 | Draft the briefing, review it, redraft with feedback (max 3 rounds) | model ×2 per round | `app/pipeline/briefing.py` |
| 8 | Add up the cost, set status to `pending` | code | `app/pipeline/runner.py`, `app/cost.py` |
| 9 | Approve | a person | `POST /api/reports/{id}/approve` |

Launch limits: wind 25 knots or less, temperature 4 °C or more, fuel 98 to 100
percent. Any reading outside its limit makes the verdict `no_go`.

### Why a note cannot change the verdict

- The verdict is computed from the three readings only. `evaluate_limits()` takes a
  `Readings` object; the note is not an argument.
- The verdict is saved when the report is filed, before any model runs, and the
  database layer refuses to update it afterwards.
- The briefing header (verdict, violations, severity, brief-by) is rendered by code.
  The model writes only the summary under it.
- Hidden instructions are looked for by a model check **and** by fixed patterns in
  code. Either one flags the report and sends it to review.

### When a model misbehaves

Model output is never trusted. Every reply is validated in code, and a reply that is
invalid, late (30 s timeout), or an error falls back to the cautious choice: sorting
becomes `unknown` / `high`, a check counts as flagged, a review counts as a
rejection. The trace card for that step shows a "fallback used" badge.

## Project layout

```
app/
  limits.py, brief_by.py, cost.py, pricing.py   plain-code rules (no model, no I/O)
  schemas.py                                    input and model-reply shapes
  llm/base.py, llm/fake.py                      the one model interface, and its fake
  llm/anthropic_client.py                       the real client (Claude)
  prompts.py                                    every prompt in one place
  pipeline/                                     classify, checks, briefing loop, runner, trace
  db.py                                         SQLite storage
  api.py, main.py                               routes and app factory
  static/                                       the console (HTML, CSS, JS; no build step)
tests/                                          one file per rubric area
TOOL_CHOICES.md                                 why each tool was chosen
```

## Rubric evidence

| Rubric item | Source | Tests |
|---|---|---|
| Start and test commands | this README | CI runs `uv run pytest` on every pull request |
| Tool choices | `TOOL_CHOICES.md` | |
| Filing reports | `app/static/app.js`, `app/schemas.py` | `test_api_validation.py`, `test_persistence_restart.py`, `test_frontend.py` |
| Launch limits in plain code | `app/limits.py` | `test_limits.py` |
| Brief-by time | `app/brief_by.py` | `test_brief_by.py` |
| Sorting with a model | `app/pipeline/classify.py`, `app/pipeline/model_step.py` | `test_classify.py` |
| Three checks and hidden instructions | `app/pipeline/checks.py` | `test_checks.py`, `test_hidden_instruction.py` |
| Draft, review, and approval | `app/pipeline/briefing.py`, `app/api.py`, `app/db.py` | `test_briefing_loop.py`, `test_approval.py` |
| Trace and cost | `app/static/app.js`, `app/cost.py`, `app/pipeline/trace.py` | `test_cost.py`, `test_pipeline_e2e.py` |
| Tests with no network or key | `app/llm/base.py`, `app/llm/fake.py`, `tests/conftest.py` | the whole suite; `test_anthropic_client.py` tests the real client against a stub |

Test run output: the CI badge at the top links to the GitHub Actions runs, where each
run shows the full `uv run pytest -v` output on a machine with no API key.

## Development workflow

Each change is made on a branch and merged through a pull request. GitHub Actions
(`.github/workflows/ci.yml`) runs the linter and the tests on every pull request.

```
uv run ruff check .     # lint
uv run ruff format .    # format
```
