"""SQLite storage for reports and their trace steps.

Two rules are enforced here rather than left to callers:
- `approve()` is the only code that can write the `approved` status.
- The verdict and violations are written once, when the report is filed.
  `update_report()` refuses to change them.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.pipeline.trace import StepRecord, utc_now_iso
from app.schemas import LimitResult, ReportIn

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    engineer_name    TEXT NOT NULL,
    station          TEXT NOT NULL,
    note             TEXT NOT NULL,
    wind_knots       REAL NOT NULL,
    temp_c           REAL NOT NULL,
    fuel_pct         REAL NOT NULL,
    verdict          TEXT NOT NULL CHECK (verdict IN ('go', 'no_go')),
    violations       TEXT NOT NULL,
    subsystem        TEXT,
    severity_model   TEXT,
    severity_final   TEXT,
    brief_by_minutes INTEGER,
    flags            TEXT NOT NULL DEFAULT '{}',
    needs_review     INTEGER NOT NULL DEFAULT 0,
    review_reasons   TEXT NOT NULL DEFAULT '[]',
    briefing         TEXT,
    review_rounds    INTEGER,
    status           TEXT NOT NULL
                     CHECK (status IN ('processing', 'pending', 'approved', 'failed')),
    error            TEXT,
    approved_by      TEXT,
    approved_at      TEXT,
    total_cost_usd   TEXT NOT NULL DEFAULT '0'
);
CREATE TABLE IF NOT EXISTS trace_steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL REFERENCES reports(id),
    seq           INTEGER NOT NULL,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('code', 'model')),
    model         TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      TEXT NOT NULL DEFAULT '0',
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT NOT NULL,
    output        TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);
"""

# Columns the pipeline may write. `verdict`, `violations`, and the approval
# columns are deliberately absent.
_UPDATABLE = {
    "subsystem",
    "severity_model",
    "severity_final",
    "brief_by_minutes",
    "flags",
    "needs_review",
    "review_reasons",
    "briefing",
    "review_rounds",
    "status",
    "error",
    "total_cost_usd",
}
_JSON_COLUMNS = {"violations", "flags", "review_reasons"}


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # --- reports ---

    def insert_report(
        self,
        report: ReportIn,
        limits: LimitResult,
        *,
        severity_final: str | None,
        brief_by_minutes: int | None,
    ) -> int:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """INSERT INTO reports (created_at, engineer_name, station, note, wind_knots,
                       temp_c, fuel_pct, verdict, violations, severity_final, brief_by_minutes,
                       status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing')""",
                (
                    utc_now_iso(),
                    report.engineer_name,
                    report.station,
                    report.note,
                    report.wind_knots,
                    report.temp_c,
                    report.fuel_pct,
                    limits.verdict,
                    json.dumps([v.model_dump() for v in limits.violations]),
                    severity_final,
                    brief_by_minutes,
                ),
            )
            return int(cursor.lastrowid)

    def update_report(self, report_id: int, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"Columns cannot be updated: {sorted(unknown)}")
        if fields.get("status") == "approved":
            raise ValueError("Only approve() may set the approved status")
        values = [
            json.dumps(value) if column in _JSON_COLUMNS else value
            for column, value in fields.items()
        ]
        assignments = ", ".join(f"{column} = ?" for column in fields)
        with closing(self._connect()) as conn, conn:
            conn.execute(f"UPDATE reports SET {assignments} WHERE id = ?", (*values, report_id))

    def get_report(self, report_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return _report_from_row(row) if row else None

    def list_reports(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
        return [_report_from_row(row) for row in rows]

    def approve(self, report_id: int, approver_name: str) -> bool:
        """Approve a pending report. Returns False if it was not pending."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """UPDATE reports SET status = 'approved', approved_by = ?, approved_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (approver_name, utc_now_iso(), report_id),
            )
            return cursor.rowcount == 1

    def reset_failed_for_rerun(self, report_id: int, keep_steps: int) -> bool:
        """Put a failed report back to processing, keeping its first `keep_steps` steps."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """UPDATE reports SET status = 'processing', error = NULL
                   WHERE id = ? AND status = 'failed'""",
                (report_id,),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                "DELETE FROM trace_steps WHERE report_id = ? AND seq > ?", (report_id, keep_steps)
            )
            return True

    def fail_stuck_reports(self) -> int:
        """Reports left in `processing` by a previous run can never finish; mark them failed."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """UPDATE reports SET status = 'failed',
                       error = 'The app stopped while this report was being processed.'
                   WHERE status = 'processing'"""
            )
            return cursor.rowcount

    # --- trace steps ---

    def add_step(self, report_id: int, step: StepRecord) -> int:
        with closing(self._connect()) as conn, conn:
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_steps WHERE report_id = ?",
                (report_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO trace_steps (report_id, seq, name, kind, model, input_tokens,
                       output_tokens, cost_usd, latency_ms, started_at, output, fallback_used,
                       error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id,
                    seq,
                    step.name,
                    step.kind,
                    step.model,
                    step.input_tokens,
                    step.output_tokens,
                    str(step.cost_usd),
                    step.latency_ms,
                    step.started_at,
                    json.dumps(step.output),
                    int(step.fallback_used),
                    step.error,
                ),
            )
            return seq

    def list_steps(self, report_id: int) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_steps WHERE report_id = ? ORDER BY seq", (report_id,)
            ).fetchall()
        steps = []
        for row in rows:
            step = dict(row)
            step.pop("id")
            step.pop("report_id")
            step["output"] = json.loads(step["output"]) if step["output"] else None
            step["fallback_used"] = bool(step["fallback_used"])
            steps.append(step)
        return steps


def _report_from_row(row: sqlite3.Row) -> dict:
    report = dict(row)
    for column in _JSON_COLUMNS:
        report[column] = json.loads(report[column])
    report["needs_review"] = bool(report["needs_review"])
    return report
