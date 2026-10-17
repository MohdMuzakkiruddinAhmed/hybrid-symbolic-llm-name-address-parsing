"""Atomic SQLite spending reservations shared by all runs in this project.

Amounts are conservative token-based estimates, not AWS invoice amounts. A
timeout keeps the whole reservation charged until a separate reconciliation.
"""

from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import json
import sqlite3
import uuid

MICROS = Decimal(1_000_000)


class BudgetExceeded(RuntimeError):
    pass


def usd_to_micros(value) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("cost must be finite and nonnegative")
    return int((amount * MICROS).to_integral_value(rounding=ROUND_CEILING))


class SpendingLedger:
    def __init__(self, path: str | Path, operational_usd=40, stage_limits=None):
        self.limit = usd_to_micros(operational_usd)
        self.stage_limits = {k: usd_to_micros(v) for k, v in (stage_limits or {}).items()}
        if self.limit > usd_to_micros(40):
            raise ValueError("project operational ceiling cannot exceed USD 40")
        if sum(self.stage_limits.values()) > self.limit:
            raise ValueError("stage allocations exceed operational ceiling")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS budget_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(
              attempt_id TEXT PRIMARY KEY, stage TEXT NOT NULL, model TEXT NOT NULL,
              reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL,
              request_id TEXT, detail TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS budget_policy_events(
              id INTEGER PRIMARY KEY, previous TEXT NOT NULL, revised TEXT NOT NULL,
              reason TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        settings = json.dumps({"limit": self.limit, "stages": self.stage_limits}, sort_keys=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT value FROM budget_settings WHERE key='limits'").fetchone()
            if row is not None and row[0] != settings:
                raise ValueError("existing project ledger has different limits; refusing to reset budget")
            self.db.execute("INSERT OR IGNORE INTO budget_settings VALUES('limits',?)", (settings,))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def total(self, stage=None) -> int:
        query = "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM requests"
        return self.db.execute(query + (" WHERE stage=?" if stage else ""), (stage,) if stage else ()).fetchone()[0]

    def reserve(self, stage: str, model: str, upper_usd) -> str:
        upper = usd_to_micros(upper_usd)
        if stage not in self.stage_limits:
            raise ValueError("unregistered_spending_stage")
        attempt = uuid.uuid4().hex
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.ensure_not_halted()
            current = json.loads(self.db.execute("SELECT value FROM budget_settings WHERE key='limits'").fetchone()[0])
            if current != {"limit": self.limit, "stages": self.stage_limits}:
                raise ValueError("stale spending-stage policy; reopen ledger using the recorded allocation")
            if self.total() + upper > self.limit or self.total(stage) + upper > self.stage_limits[stage]:
                raise BudgetExceeded("request reservation would exceed the project or stage allocation")
            self.db.execute("INSERT INTO requests(attempt_id,stage,model,reserved,state) VALUES(?,?,?,?,'reserved')",
                            (attempt, stage, model, upper))
            self.db.execute("COMMIT")
            return attempt
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def reallocate_stages(self, new_limits: dict, reason: str):
        """Audited redistribution within the same ceiling; never erases charges.

        Requires idle dispatch, identical stage names, and allocations covering
        every existing settled/uncertain reservation. Existing objects must be
        reopened afterwards; reserve() rejects their stale stage policy.
        """
        revised = {key: usd_to_micros(value) for key, value in new_limits.items()}
        if not reason.strip() or set(revised) != set(self.stage_limits) or sum(revised.values()) > self.limit:
            raise ValueError("invalid stage redistribution")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.ensure_not_halted()
            if self.db.execute("SELECT COUNT(*) FROM requests WHERE state='reserved'").fetchone()[0]:
                raise ValueError("cannot redistribute stages while requests are in flight")
            if any(self.total(stage) > limit for stage, limit in revised.items()):
                raise BudgetExceeded("revised stage would be below existing committed costs")
            previous = self.db.execute("SELECT value FROM budget_settings WHERE key='limits'").fetchone()[0]
            updated = json.dumps({"limit": self.limit, "stages": revised}, sort_keys=True)
            self.db.execute("UPDATE budget_settings SET value=? WHERE key='limits'", (updated,))
            self.db.execute("INSERT INTO budget_policy_events(previous,revised,reason) VALUES(?,?,?)", (previous, updated, reason))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def settle(self, attempt: str, observed_usd, request_id: str | None = None, detail: str = ""):
        charged = usd_to_micros(observed_usd)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM requests WHERE attempt_id=?", (attempt,)).fetchone()
            if row is None or row["state"] != "reserved":
                raise ValueError("attempt is missing or already finalized")
            if charged > row["reserved"]:
                # Persist the overrun and stop subsequent requests rather than
                # losing the actual estimate because an exception rolls it back.
                self.db.execute("INSERT OR REPLACE INTO budget_settings VALUES('halt','reservation_overrun')")
            self.db.execute("UPDATE requests SET charged=?,state='settled',request_id=?,detail=? WHERE attempt_id=?",
                            (charged, request_id, detail, attempt))
            self.db.execute("COMMIT")
            if charged > row["reserved"]:
                raise BudgetExceeded("observed usage exceeded reservation; ledger halted")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def uncertain(self, attempt: str, detail: str):
        self.db.execute("UPDATE requests SET state='uncertain',detail=? WHERE attempt_id=? AND state='reserved'",
                        (detail, attempt))

    def release_before_dispatch(self, attempt: str):
        self.db.execute("UPDATE requests SET state='released',charged=0 WHERE attempt_id=? AND state='reserved'", (attempt,))

    def ensure_not_halted(self):
        if self.db.execute("SELECT value FROM budget_settings WHERE key='halt'").fetchone():
            raise BudgetExceeded("project ledger is halted for reconciliation")

    def summary(self):
        return {
            "operational_ceiling_usd": self.limit / 1_000_000,
            "committed_estimate_usd": self.total() / 1_000_000,
            "attempts": self.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
            "states": {r[0]: r[1] for r in self.db.execute("SELECT state,COUNT(*) FROM requests GROUP BY state")},
            "note": "Token/rate estimates and retained reservations; not an AWS invoice.",
        }
