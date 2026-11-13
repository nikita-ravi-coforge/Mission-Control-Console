# Mission Control: Go/No-Go Launch Console

Engineers file anomaly reports; a pipeline sorts each one and drafts a briefing;
the Flight Director approves it. The go/no-go verdict always comes from plain
code, never from a model.

## Prerequisite

[uv](https://docs.astral.sh/uv/getting-started/installation/) — it installs
Python and all dependencies on first run.

## Start the app

```
uv run python -m app
```

Then open http://localhost:8000.

## Run the tests

```
uv run pytest
```

The tests need no network and no API key.
