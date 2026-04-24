from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .session import SessionStore
from .types import RunEvent, SessionRecord


class ArtifactWriter:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def run_dir(self, session_id: str) -> Path:
        path = self.store.paths.runs_dir / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sync(self, session_id: str) -> dict[str, str]:
        session = self.store.get(session_id)
        events = self.store.events(session_id)
        run_dir = self.run_dir(session_id)
        manifest_path = run_dir / "run_manifest.json"
        events_path = run_dir / "events.jsonl"
        summary_path = run_dir / "summary.md"
        manifest = self._manifest(session, events)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        events_path.write_text(
            "".join(json.dumps(event.to_dict(), ensure_ascii=False) + "\n" for event in events),
            encoding="utf-8",
        )
        summary_path.write_text(self._summary(session, events, manifest), encoding="utf-8")
        return {
            "run_dir": str(run_dir),
            "manifest": str(manifest_path),
            "events": str(events_path),
            "summary": str(summary_path),
        }

    def _manifest(self, session: SessionRecord, events: list[RunEvent]) -> dict[str, Any]:
        return {
            "version": "1.0",
            "session_id": session.session_id,
            "request": session.request,
            "task_type": session.task_type,
            "strategy": session.strategy,
            "mode": session.mode,
            "status": session.status,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "plan": session.plan_json,
            "event_count": len(events),
            "artifacts": {
                "events": "events.jsonl",
                "summary": "summary.md",
            },
        }

    def _summary(self, session: SessionRecord, events: list[RunEvent], manifest: dict[str, Any]) -> str:
        completed = [event for event in events if event.event_type == "stage_result" and event.status == "completed"]
        reviews = [event for event in events if event.event_type == "review_feedback"]
        errors = [event for event in events if event.event_type == "error"]
        lines = [
            f"# AEGIS 1.0 Run {session.session_id}",
            "",
            f"- Request: {session.request}",
            f"- Status: {session.status}",
            f"- Strategy: {session.strategy}",
            f"- Mode: {session.mode}",
            f"- Stages completed: {len(completed)}/{len(session.plan_json.get('steps', []))}",
            f"- Review events: {len(reviews)}",
            f"- Errors: {len(errors)}",
            "",
            "## Artifacts",
            "",
            f"- Manifest: `{manifest['artifacts']['events']}`",
            f"- Events: `{manifest['artifacts']['events']}`",
            "",
            "## Recent Events",
            "",
        ]
        for event in events[-12:]:
            lines.append(f"- {event.created_at} `{event.event_type}` {event.summary}")
        return "\n".join(lines) + "\n"
