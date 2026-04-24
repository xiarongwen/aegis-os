from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from .config import AppPaths, ensure_runtime_dirs
from .types import MessageType, RoutingDecision, SessionMessage, SessionRecord, StageResult


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SharedContext:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._values = deepcopy(initial or {})

    def update(self, key: str, value: Any) -> None:
        self._values[key] = deepcopy(value)

    def merge(self, payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            self.update(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._values.get(key, default))

    def export(self) -> dict[str, Any]:
        return deepcopy(self._values)


class SessionStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        ensure_runtime_dirs(paths)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.session_db_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    models_json TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipient TEXT,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def create_session(
        self,
        *,
        request: str,
        decision: RoutingDecision,
        metadata: dict[str, Any] | None = None,
        status: str = "planned",
    ) -> SessionRecord:
        timestamp = utc_now()
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        payload = metadata or {}
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, request, task_type, strategy, models_json,
                    mode, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    request,
                    decision.task_type.value,
                    decision.strategy.value,
                    json.dumps(decision.models, ensure_ascii=False),
                    decision.mode,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_session(session_id)

    def add_checkpoint(self, session_id: str, stage: str, payload: dict[str, Any]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (session_id, stage, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, stage, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def add_message(
        self,
        *,
        session_id: str,
        channel: str,
        sender: str,
        message_type: MessageType | str,
        content: str,
        recipient: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        timestamp = utc_now()
        raw_type = message_type.value if isinstance(message_type, MessageType) else str(message_type)
        payload = metadata or {}
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    session_id, channel, sender, recipient, message_type,
                    content, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    channel,
                    sender,
                    recipient,
                    raw_type,
                    content,
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                ),
            )
        return SessionMessage(
            session_id=session_id,
            channel=channel,
            sender=sender,
            recipient=recipient,
            message_type=raw_type,
            content=content,
            metadata=payload,
            created_at=timestamp,
        )

    def update_status(self, session_id: str, status: str, metadata: dict[str, Any] | None = None) -> SessionRecord:
        record = self.get_session(session_id)
        merged_metadata = dict(record.metadata)
        if metadata:
            merged_metadata.update(metadata)
        timestamp = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (status, json.dumps(merged_metadata, ensure_ascii=False), timestamp, session_id),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return SessionRecord(
            session_id=str(row["session_id"]),
            request=str(row["request"]),
            task_type=str(row["task_type"]),
            strategy=str(row["strategy"]),
            models=json.loads(row["models_json"]),
            mode=str(row["mode"]),
            status=str(row["status"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_sessions(self, *, limit: int = 20) -> list[SessionRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            SessionRecord(
                session_id=str(row["session_id"]),
                request=str(row["request"]),
                task_type=str(row["task_type"]),
                strategy=str(row["strategy"]),
                models=json.loads(row["models_json"]),
                mode=str(row["mode"]),
                status=str(row["status"]),
                metadata=json.loads(row["metadata_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT stage, payload_json, created_at FROM checkpoints WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            {
                "stage": str(row["stage"]),
                "payload": json.loads(row["payload_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def list_messages(self, session_id: str) -> list[SessionMessage]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT session_id, channel, sender, recipient, message_type, content, metadata_json, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            SessionMessage(
                session_id=str(row["session_id"]),
                channel=str(row["channel"]),
                sender=str(row["sender"]),
                recipient=str(row["recipient"]) if row["recipient"] is not None else None,
                message_type=str(row["message_type"]),
                content=str(row["content"]),
                metadata=json.loads(row["metadata_json"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def cost_summary(self) -> dict[str, Any]:
        sessions = self.list_sessions(limit=1000)
        estimated_total = round(
            sum(float(session.metadata.get("estimated_cost", 0.0) or 0.0) for session in sessions),
            2,
        )
        actual_total = round(
            sum(float(session.metadata.get("actual_cost", 0.0) or 0.0) for session in sessions),
            2,
        )
        return {
            "session_count": len(sessions),
            "estimated_total": estimated_total,
            "actual_total": actual_total,
        }


MessageCallback = Callable[[SessionMessage], None]


class MessageBus:
    def __init__(self, store: SessionStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id
        self._subscribers: dict[str, list[MessageCallback]] = {}

    def subscribe(self, channel: str, callback: MessageCallback) -> None:
        self._subscribers.setdefault(channel, []).append(callback)

    def publish(
        self,
        *,
        channel: str,
        sender: str,
        message_type: MessageType | str,
        content: str,
        recipient: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        message = self.store.add_message(
            session_id=self.session_id,
            channel=channel,
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            content=content,
            metadata=metadata,
        )
        callbacks = list(self._subscribers.get(channel, [])) + list(self._subscribers.get("*", []))
        for callback in callbacks:
            callback(message)
        return message


class MultiModelSession:
    def __init__(self, record: SessionRecord, store: SessionStore) -> None:
        self.record = record
        self.store = store
        self.shared_context = SharedContext(record.metadata.get("shared_context", {}))
        self.message_bus = MessageBus(store, record.session_id)

    @property
    def session_id(self) -> str:
        return self.record.session_id

    def checkpoint(self, stage: str, payload: dict[str, Any]) -> None:
        self.store.add_checkpoint(self.record.session_id, stage, payload)

    def publish(
        self,
        *,
        channel: str,
        sender: str,
        message_type: MessageType | str,
        content: str,
        recipient: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        return self.message_bus.publish(
            channel=channel,
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            content=content,
            metadata=metadata,
        )

    def update_metadata(self, **metadata: Any) -> SessionRecord:
        self.record = self.store.update_status(self.record.session_id, self.record.status, metadata=metadata)
        return self.record

    def set_status(self, status: str, **metadata: Any) -> SessionRecord:
        self.record = self.store.update_status(self.record.session_id, status, metadata=metadata)
        return self.record

    def share_context(self, key: str, value: Any, *, sender: str = "system") -> None:
        self.shared_context.update(key, value)
        exported = self.shared_context.export()
        self.record = self.store.update_status(
            self.record.session_id,
            self.record.status,
            metadata={"shared_context": exported},
        )
        self.publish(
            channel="context",
            sender=sender,
            message_type=MessageType.CODE_SHARE,
            content=f"shared context updated: {key}",
            metadata={"key": key},
        )

    def record_stage_result(self, result: StageResult) -> None:
        outputs = self.shared_context.get("outputs", {})
        outputs[result.stage_name] = result.to_dict()
        self.shared_context.update("outputs", outputs)
        self.publish(
            channel="stages",
            sender=result.model,
            message_type=MessageType.STAGE_RESULT,
            content=result.output,
            metadata={"stage": result.stage_name, "kind": result.kind},
        )
        self.checkpoint(
            f"stage:{result.stage_name}",
            {
                "stage_result": result.to_dict(),
                "shared_context": self.shared_context.export(),
            },
        )
        self.record = self.store.update_status(
            self.record.session_id,
            self.record.status,
            metadata={
                "shared_context": self.shared_context.export(),
                "last_stage": result.stage_name,
            },
        )

    def complete(self, final_output: str, *, metadata: dict[str, Any] | None = None) -> SessionRecord:
        self.shared_context.update("final_output", final_output)
        payload = {
            "shared_context": self.shared_context.export(),
            "final_output": final_output,
            "execution_state": "completed",
        }
        if metadata:
            payload.update(metadata)
        self.checkpoint("complete", payload)
        self.record = self.store.update_status(self.record.session_id, "completed", metadata=payload)
        return self.record

    def fail(self, error: str, *, metadata: dict[str, Any] | None = None) -> SessionRecord:
        payload = {
            "error": error,
            "shared_context": self.shared_context.export(),
            "execution_state": "failed",
        }
        if metadata:
            payload.update(metadata)
        self.publish(
            channel="errors",
            sender="system",
            message_type=MessageType.ERROR,
            content=error,
            metadata=metadata or {},
        )
        self.checkpoint("failed", payload)
        self.record = self.store.update_status(self.record.session_id, "failed", metadata=payload)
        return self.record
