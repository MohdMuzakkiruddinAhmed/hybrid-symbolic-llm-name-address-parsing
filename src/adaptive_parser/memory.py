"""Durable structural memory with promotion and conservative conflict blocking."""

import json
import sqlite3
from pathlib import Path

from .tokenization import input_fingerprint
from .validation import VALIDATOR_VERSION


class RuleMemory:
    def __init__(self, path: str | Path, support: int = 3):
        if type(support) is not int or support < 1:
            raise ValueError("support must be positive")
        self.support = support
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS memory_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rules(
              id INTEGER PRIMARY KEY, signature TEXT NOT NULL, mapping TEXT NOT NULL,
              status TEXT NOT NULL, validator_version TEXT NOT NULL,
              UNIQUE(signature,mapping));
            CREATE TABLE IF NOT EXISTS evidence(
              signature TEXT NOT NULL, fingerprint TEXT NOT NULL, record_id TEXT NOT NULL,
              rule_id INTEGER NOT NULL, PRIMARY KEY(signature,fingerprint));
            CREATE TABLE IF NOT EXISTS memory_events(
              id INTEGER PRIMARY KEY, signature TEXT, rule_id INTEGER,
              event TEXT NOT NULL, reason TEXT);
        """)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute("SELECT value FROM memory_settings WHERE key='support'").fetchone()
            if previous is not None and previous[0] != str(support):
                raise ValueError("memory promotion policy changed; use a separate versioned memory")
            self.db.execute("INSERT OR IGNORE INTO memory_settings VALUES('support',?)", (str(support),))
            version = self.db.execute("SELECT value FROM memory_settings WHERE key='validator_version'").fetchone()
            if version is not None and version[0] != VALIDATOR_VERSION:
                raise ValueError("memory validator version changed; use a separate versioned memory")
            if version is None and self.db.execute("SELECT COUNT(*) FROM rules").fetchone()[0]:
                raise ValueError("legacy memory lacks validator binding; use a separate versioned memory")
            self.db.execute("INSERT OR IGNORE INTO memory_settings VALUES('validator_version',?)", (VALIDATOR_VERSION,))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def lookup(self, signature: str):
        rows = self.db.execute("SELECT * FROM rules WHERE signature=?", (signature,)).fetchall()
        if any(r["status"] == "quarantined" for r in rows):
            return "blocked", None
        active = [r for r in rows if r["status"] == "active"]
        if len(active) != 1:
            return "miss", None
        rule = dict(active[0])
        rule["mapping"] = {int(k): v for k, v in json.loads(rule["mapping"]).items()}
        return "hit", rule

    def observe(self, signature: str, mapping: dict, record_id: str, raw: str):
        encoded = json.dumps(mapping, sort_keys=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO rules(signature,mapping,status,validator_version) VALUES(?,?,'provisional',?)",
                (signature, encoded, VALIDATOR_VERSION),
            )
            rule = self.db.execute("SELECT * FROM rules WHERE signature=? AND mapping=?", (signature, encoded)).fetchone()
            self.db.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)",
                            (signature, input_fingerprint(raw), record_id, rule["id"]))
            alternatives = self.db.execute("SELECT COUNT(*) FROM rules WHERE signature=?", (signature,)).fetchone()[0]
            if alternatives > 1 or rule["status"] == "quarantined":
                self.db.execute("UPDATE rules SET status='quarantined' WHERE signature=?", (signature,))
                status = "quarantined"
            else:
                count = self.db.execute("SELECT COUNT(*) FROM evidence WHERE rule_id=?", (rule["id"],)).fetchone()[0]
                status = "active" if count >= self.support else "provisional"
                self.db.execute("UPDATE rules SET status=? WHERE id=?", (status, rule["id"]))
            self.db.execute("INSERT INTO memory_events(signature,rule_id,event) VALUES(?,?,?)",
                            (signature, rule["id"], status))
            self.db.execute("COMMIT")
            return rule["id"], status
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def quarantine(self, signature: str, reason: str):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("UPDATE rules SET status='quarantined' WHERE signature=?", (signature,))
            self.db.execute("INSERT INTO memory_events(signature,event,reason) VALUES(?,'quarantined',?)",
                            (signature, reason))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
