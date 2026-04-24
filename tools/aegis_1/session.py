from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from .config import AppPaths, ensure_dirs
from .types import RouteDecision, RunEvent, RunPlan, RunStatus, SessionRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SessionStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        ensure_dirs(paths)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.paths.session_db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    stage_name TEXT,
                    role TEXT,
                    model TEXT,
                    status TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def create(self, request: str, route: RouteDecision, plan: RunPlan, metadata: dict[str, Any] | None = None) -> SessionRecord:
        timestamp = utc_now()
        session_id = f"a1-{uuid.uuid4().hex[:10]}"
        payload = metadata or {}
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, request, task_type, strategy, mode, status,
                    plan_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    request,
                    route.task_type.value,
                    route.strategy.value,
                    route.mode,
                    RunStatus.PLANNED.value,
                    json.dumps(plan.to_dict(), ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        self.add_event(session_id, "route", f"routed as {route.task_type.value} -> {route.strategy.value}", metadata={"rationale": route.rationale})
        self.add_event(session_id, "plan_created", f"created {len(plan.steps)} step run plan", metadata={"plan": plan.to_dict()})
        return self.get(session_id)

    def update_status(self, session_id: str, status: RunStatus | str, metadata: dict[str, Any] | None = None) -> SessionRecord:
        record = self.get(session_id)
        merged = dict(record.metadata)
        if metadata:
            merged.update(metadata)
        value = status.value if isinstance(status, RunStatus) else str(status)
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, metadata_json = ?, updated_at = ? WHERE session_id = ?",
                (value, json.dumps(merged, ensure_ascii=False), utc_now(), session_id),
            )
        return self.get(session_id)

    def add_event(
        self,
        session_id: str,
        event_type: str,
        summary: str,
        *,
        detail: str = "",
        stage_name: str | None = None,
        role: str | None = None,
        model: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunEvent:
        timestamp = utc_now()
        payload = metadata or {}
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    session_id, event_type, summary, detail, stage_name, role,
                    model, status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_type,
                    summary,
                    detail,
                    stage_name,
                    role,
                    model,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                ),
            )
            event_id = int(cursor.lastrowid)
        event = RunEvent(event_id, session_id, event_type, summary, detail, stage_name, role, model, status, payload, timestamp)
        try:
            from .artifacts import ArtifactWriter

            ArtifactWriter(self).sync(session_id)
        except Exception:
            pass
        return event

    def get(self, session_id: str) -> SessionRecord:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return SessionRecord(
            session_id=str(row["session_id"]),
            request=str(row["request"]),
            task_type=str(row["task_type"]),
            strategy=str(row["strategy"]),
            mode=str(row["mode"]),
            status=str(row["status"]),
            plan_json=json.loads(row["plan_json"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list(self, limit: int = 20) -> list[SessionRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.get(str(row["session_id"])) for row in rows]

    def events(self, session_id: str) -> list[RunEvent]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY event_id ASC", (session_id,)).fetchall()
        return [
            RunEvent(
                event_id=int(row["event_id"]),
                session_id=str(row["session_id"]),
                event_type=str(row["event_type"]),
                summary=str(row["summary"]),
                detail=str(row["detail"]),
                stage_name=str(row["stage_name"]) if row["stage_name"] is not None else None,
                role=str(row["role"]) if row["role"] is not None else None,
                model=str(row["model"]) if row["model"] is not None else None,
                status=str(row["status"]) if row["status"] is not None else None,
                metadata=json.loads(row["metadata_json"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def cost_summary(self) -> dict[str, Any]:
        sessions = self.list(limit=1000)
        by_status: dict[str, int] = {}
        for session in sessions:
            by_status[session.status] = by_status.get(session.status, 0) + 1
        event_count = 0
        for session in sessions:
            event_count += len(self.events(session.session_id))
        return {
            "session_count": len(sessions),
            "event_count": event_count,
            "by_status": by_status,
            "estimated_total": 0.0,
            "actual_total": 0.0,
        }
