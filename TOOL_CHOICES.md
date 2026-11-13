# Tool choices

Each choice has a specific reason, one alternative that was rejected, and one concern
a customer would raise, with how it is handled.

## Back end: Python 3.12 + FastAPI

**Reason.** The app's hardest rule is "never trust model output". Pydantic, which
FastAPI is built on, validates the engineer's form and every model reply with the
same mechanism, so one kind of schema guards both doors (`app/schemas.py`). FastAPI
is also async, which is what lets the three note checks run at the same time with
`asyncio.gather`.

**Rejected: Node.js + Express.** It handles concurrency just as well, but validation
of model replies would need a separate library and hand-written glue, and the cost
maths would need a decimal library to avoid floating-point money. Python has
`Decimal` built in.

**Customer concern: "What happens when the model provider is slow or down during the
count?"** The verdict is computed and saved by plain code before any model is called,
so it never waits on a model. Every model call has a 30-second timeout and falls back
to the cautious result, and the report still reaches the Flight Director marked
"needs review" (`tests/test_pipeline_e2e.py`,
`test_every_model_failing_still_yields_a_verdict_and_a_pending_report`).

## Front end: plain HTML, CSS, and JavaScript served by FastAPI

**Reason.** The console is one screen: a form, a list, and a detail panel. Serving it
as static files from the same process means one command starts everything, with no
build step and no second server to keep in sync.

**Rejected: React + Vite.** It would add a Node toolchain, a build step, and a second
dev server, which works against a one-command start, for a screen with three panels
and no client-side routing.

**Customer concern: "Engineers type free text. Can a note inject script into the
Flight Director's screen?"** All report and model text is written to the page with
`textContent`, never `innerHTML`, so it is always shown as text. A test fails if
`innerHTML` appears in the console script (`tests/test_frontend.py`). The trade-off
of plain JavaScript is that it gets harder to maintain as the screen grows; past a
handful of views a component framework would be the right move.

## Database: SQLite

**Reason.** Reports must survive a restart, and the app runs in one console room.
SQLite is a single file with nothing to install, so the start command stays one
command, and each test gets its own throwaway database file, which is how the restart
test builds a second app on the same file (`tests/test_persistence_restart.py`).

**Rejected: PostgreSQL.** It is the better database for many writers, but it needs a
running server, which breaks the one-command start and makes the tests depend on
infrastructure.

**Customer concern: "Is the record of who approved what safe, and will this scale to
several launch sites?"** Approval and the verdict are protected in the storage layer
itself: only `approve()` can write the approved status, and the verdict cannot be
updated after filing (`app/db.py`). SQLite allows one writer at a time, which is fine
for one room filing a few reports a minute but not for several sites. All SQL sits
behind one `Database` class, so moving to PostgreSQL changes one file.

## Model: two tiers behind one interface

**Reason.** The pipeline makes two different kinds of call. Sorting and the three
checks are short classification questions with a small JSON answer, asked four times
per report, so they go to a fast, cheap model. Drafting and reviewing the briefing
need better writing and judgement and are what the Flight Director actually reads, so
they go to a stronger model. Each call names its tier (`fast` or `strong`) and the
client maps the tier to a model, so the split is one line per call and the cost of
each tier is visible on the trace cards.

**Rejected: one strong model for every call.** It is simpler, but it pays the strong
model's price and latency for four yes/no-style questions per report, in a window
where the brief-by time can be five minutes.

**Customer concern: "Our anomaly notes are sensitive. Where do they go, and what does
each report cost?"** Notes are sent only to the configured model endpoint, and every
model call goes through one interface (`app/llm/base.py`), so the provider can be
swapped for one inside the customer's own cloud tenant without touching the pipeline.
The cost of every report is calculated in code from token counts and shown in the
console, and an unpriced model raises an error instead of being counted as free
(`app/cost.py`).

> The real model client is the one piece not yet in the repo: the app currently runs
> on the scripted fake model. This section will name the two deployed models and
> their prices once the provider deployment is confirmed.
