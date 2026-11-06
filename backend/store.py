"""Small SQLite record store. Immutable plans and durable scoped corrections."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from .contracts import Brief, Correction, now


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("incoming", "proxies", "analysis", "projects", "exports", "models"):
            (self.root / name).mkdir(exist_ok=True)
        self.path = self.root / "state.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(kind,id))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def put(self, kind: str, record: BaseModel | dict, immutable: bool = False) -> dict:
        data = record.model_dump(mode="json") if isinstance(record, BaseModel) else dict(record)
        statement = "INSERT INTO records(kind,id,data,created) VALUES(?,?,?,?)"
        if not immutable:
            statement += " ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data"
        with self.connect() as db:
            db.execute(statement, (kind, data["id"], json.dumps(data, allow_nan=False), now()))
        return data

    def get(self, kind: str, record_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT data FROM records WHERE kind=? ORDER BY created,id", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def setting(self, name: str, default=None):
        record = self.get("settings", name)
        return record["value"] if record else default

    def set_setting(self, name: str, value):
        self.put("settings", {"id": name, "value": value})

    def applicable_corrections(self, brief: Brief, plan_id: str | None = None) -> list[dict]:
        format_key = f"{brief.reference_mode}:{brief.width}x{brief.height}:{brief.fps_num}/{brief.fps_den}"
        selected = []
        for value in self.list("corrections"):
            correction = Correction.model_validate(value)
            if correction.approval_state != "approved":
                continue
            if correction.scope == "reusable_rule" or (correction.scope == "format" and correction.format_key == format_key) or (correction.scope == "edit" and correction.project_id == brief.id and (plan_id is None or correction.plan_id == plan_id or correction.new_plan_id == plan_id)):
                selected.append(value)
        return selected
