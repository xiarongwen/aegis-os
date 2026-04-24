from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.aegis_v2.executor import MultiModelExecutor, _condition_matches
from tools.aegis_v2.runtime import RuntimeExecutionError, RuntimeManager
from tools.aegis_v2.session import MultiModelSession
from tools.aegis_v2.types import (
    ExecutionPlan,
    ExecutionStep,
    MessageType,
    ModelHealth,
    ModelSpec,
    PatternExecutionResult,
    RoutingDecision,
    RoutingStrategy,
    RuntimeInvocation,
    RuntimeResult,
    SessionMessage,
    SessionRecord,
    StageResult,
    TaskType,
)


def routing_decision(
    *,
    strategy: RoutingStrategy = RoutingStrategy.SINGLE,
    models: list[str] | None = None,
    complexity: int = 5,
) -> RoutingDecision:
    return RoutingDecision(
        task_type=TaskType.CODE_GENERATION,
        strategy=strategy,
        models=models or ["codex"],
        mode="balanced",
        complexity=complexity,
        estimated_cost=0.12,
        estimated_time_seconds=30,
    )


def session_record(*, status: str = "planned", metadata: dict | None = None) -> SessionRecord:
    return SessionRecord(
        session_id="sess-unit",
        request="implement tests",
        task_type="code_gen",
        strategy="single",
        models=["codex"],
        mode="balanced",
        status=status,
        metadata=metadata or {},
        created_at="2026-04-24T00:00:00Z",
        updated_at="2026-04-24T00:00:00Z",
    )


class InMemorySessionStore:
    def __init__(self, record: SessionRecord | None = None) -> None:
        self.record = record or session_record()
        self.checkpoints: list[tuple[str, dict]] = []
        self.messages: list[SessionMessage] = []
        self.status_updates: list[tuple[str, dict | None]] = []

    def add_checkpoint(self, session_id: str, stage: str, payload: dict) -> None:
        assert session_id == self.record.session_id
        self.checkpoints.append((stage, payload))

    def add_message(
        self,
        *,
        session_id: str,
        channel: str,
        sender: str,
        message_type: MessageType | str,
        content: str,
        recipient: str | None = None,
        metadata: dict | None = None,
    ) -> SessionMessage:
        assert session_id == self.record.session_id
        raw_type = message_type.value if isinstance(message_type, MessageType) else str(message_type)
        message = SessionMessage(
            session_id=session_id,
            channel=channel,
            sender=sender,
            recipient=recipient,
            message_type=raw_type,
            content=content,
            metadata=metadata or {},
            created_at="2026-04-24T00:00:01Z",
        )
        self.messages.append(message)
        return message

    def update_status(self, session_id: str, status: str, metadata: dict | None = None) -> SessionRecord:
        assert session_id == self.record.session_id
        merged = dict(self.record.metadata)
        if metadata:
            merged.update(metadata)
        self.record = SessionRecord(
            session_id=self.record.session_id,
            request=self.record.request,
            task_type=self.record.task_type,
            strategy=self.record.strategy,
            models=list(self.record.models),
            mode=self.record.mode,
            status=status,
            metadata=merged,
            created_at=self.record.created_at,
            updated_at="2026-04-24T00:00:02Z",
        )
        self.status_updates.append((status, metadata))
        return self.record

    def get_session(self, session_id: str) -> SessionRecord:
        assert session_id == self.record.session_id
        return self.record


class FakeRegistry:
    def __init__(self) -> None:
        self.paths = SimpleNamespace(
            workspace_root=Path("/workspace"),
            logs_dir=Path("/runtime/logs"),
            responses_dir=Path("/runtime/responses"),
        )
        self.config = {"runtime": {"retries": 2, "timeout_seconds": {"default": 7}}}
        self._models = {
            "codex": ModelSpec(
                name="codex",
                provider="openai",
                runtime="codex-cli",
                capabilities=["code_generation", "debugging", "testing"],
                cost_per_1k_tokens=0.02,
            ),
            "claude": ModelSpec(
                name="claude",
                provider="anthropic",
                runtime="claude-code-cli",
                capabilities=["complex_reasoning", "code_review"],
                cost_per_1k_tokens=0.04,
            ),
            "local": ModelSpec(
                name="local",
                provider="ollama",
                runtime="local",
                capabilities=["testing"],
                cost_per_1k_tokens=0.0,
            ),
        }
        self.bundle = SimpleNamespace(enabled_model_names=lambda: list(self._models))
        self.health = {
            name: ModelHealth(name=name, available=True, runtime=spec.runtime, provider=spec.provider, details="ok")
            for name, spec in self._models.items()
        }

    def get(self, name: str) -> ModelSpec:
        return self._models[name]

    def names(self) -> list[str]:
        return list(self._models)

    def check_model(self, name: str) -> ModelHealth:
        return self.health[name]


class RuntimeStateMachineUnitTests(unittest.TestCase):
    def test_simulated_completion_bypasses_health_and_execution_io(self) -> None:
        registry = FakeRegistry()
        registry.check_model = Mock(side_effect=AssertionError("health check should not run in simulate mode"))
        manager = RuntimeManager(
            registry,
            simulate=True,
            responder=lambda model, prompt, metadata: f"{model}:{metadata['stage_name']}:{prompt}",
        )

        result = manager.complete(
            "codex",
            "write unit tests",
            session_id="sess-unit",
            stage_name="code",
            metadata={"kind": "coder"},
        )

        self.assertEqual(manager.mode_label(), "simulate")
        self.assertEqual(result.output, "codex:code:write unit tests")
        self.assertEqual(result.command, ["simulate", "codex"])
        self.assertEqual(result.metadata["stage_name"], "code")
        self.assertEqual(result.metadata["kind"], "coder")
        registry.check_model.assert_not_called()

    def test_unavailable_model_transitions_to_ranked_fallback_before_execution(self) -> None:
        registry = FakeRegistry()
        registry.health["local"] = ModelHealth(
            name="local",
            available=False,
            runtime="local",
            provider="ollama",
            details="binary=ollama:missing",
        )
        manager = RuntimeManager(registry)
        manager._execute_once = Mock(
            return_value=RuntimeResult(
                model="codex",
                runtime="codex-cli",
                output="fallback result",
                exit_code=0,
                duration_ms=1,
                command=["fake"],
                log_path="",
                metadata={},
            )
        )

        result = manager.complete(
            "local",
            "test fallback",
            session_id="sess-unit",
            stage_name="review",
            metadata={"kind": "worker"},
        )

        executed_spec = manager._execute_once.call_args.args[0]
        payload = manager._execute_once.call_args.kwargs["payload"]
        self.assertEqual(executed_spec.name, "codex")
        self.assertEqual(result.output, "fallback result")
        self.assertEqual(payload["fallback_from"], "local")
        self.assertEqual(payload["fallback_to"], "codex")
        self.assertEqual(payload["fallback_reason"], "binary=ollama:missing")

    def test_retry_state_is_recorded_and_terminal_runtime_error_is_raised(self) -> None:
        registry = FakeRegistry()
        manager = RuntimeManager(registry)
        manager._execute_once = Mock(
            side_effect=RuntimeExecutionError("temporary runtime failure", model_name="codex", stage_name="code")
        )

        with self.assertRaises(RuntimeExecutionError):
            manager.complete("codex", "implement", session_id="sess-unit", stage_name="code")

        self.assertEqual(manager._execute_once.call_count, 2)
        first_payload = manager._execute_once.call_args_list[0].kwargs["payload"]
        second_payload = manager._execute_once.call_args_list[1].kwargs["payload"]
        self.assertEqual(first_payload["attempt"], 2)
        self.assertEqual(second_payload["attempt"], 2)
        self.assertFalse(second_payload["retrying"])
        self.assertIn("temporary runtime failure", second_payload["last_error"])

    def test_execute_once_uses_subprocess_and_extracts_adapter_output_with_io_mocked(self) -> None:
        registry = FakeRegistry()
        manager = RuntimeManager(registry)
        adapter = Mock()
        adapter.supports_bridge.return_value = False
        adapter.build_invocation.return_value = RuntimeInvocation(
            model="codex",
            runtime="codex-cli",
            command=["codex", "exec", "prompt"],
            cwd="/workspace",
            log_path="/runtime/logs/unit.log",
            response_path="/runtime/responses/unit.txt",
        )
        adapter.extract_output.return_value = "adapter output"
        manager._adapters["codex-cli"] = adapter

        class StubPopen:
            def __init__(self) -> None:
                self.stdout = io.StringIO("stdout text\n")
                self.stderr = io.StringIO("")
                self._returncode = 0

            def poll(self) -> int | None:
                if self.stdout.tell() == len(self.stdout.getvalue()) and self.stderr.tell() == len(self.stderr.getvalue()):
                    return self._returncode
                return None

            def wait(self, timeout: float | None = None) -> int:
                del timeout
                return self._returncode

        with patch("tools.aegis_v2.runtime.subprocess.Popen", return_value=StubPopen()) as run, patch.object(
            Path, "mkdir"
        ) as mkdir, patch.object(Path, "write_text") as write_text:
            result = manager._execute_once(
                registry.get("codex"),
                "prompt",
                session_id="sess-unit",
                stage_name="code",
                payload={"kind": "coder"},
            )

        run.assert_called_once()
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        write_text.assert_called_once()
        adapter.extract_output.assert_called_once()
        self.assertEqual(result.output, "adapter output")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.metadata["kind"], "coder")


class SessionLifecycleUnitTests(unittest.TestCase):
    def test_share_context_persists_snapshot_and_publishes_context_message(self) -> None:
        store = InMemorySessionStore(session_record(metadata={"shared_context": {"existing": {"nested": True}}}))
        session = MultiModelSession(store.record, store)
        external_payload = {"items": [1, 2]}

        session.share_context("new_key", external_payload, sender="tester")
        external_payload["items"].append(3)

        self.assertEqual(store.record.status, "planned")
        self.assertEqual(store.record.metadata["shared_context"]["existing"], {"nested": True})
        self.assertEqual(store.record.metadata["shared_context"]["new_key"], {"items": [1, 2]})
        self.assertEqual(store.messages[-1].channel, "context")
        self.assertEqual(store.messages[-1].message_type, MessageType.CODE_SHARE.value)
        self.assertEqual(store.messages[-1].metadata, {"key": "new_key"})

    def test_record_stage_result_updates_outputs_message_checkpoint_and_last_stage(self) -> None:
        store = InMemorySessionStore()
        session = MultiModelSession(store.record, store)
        result = StageResult(
            stage_name="code",
            model="codex",
            kind="coder",
            output="implemented",
            exit_code=0,
            duration_ms=12,
            approximate_cost=0.01,
        )

        session.record_stage_result(result)

        self.assertEqual(session.shared_context.get("outputs")["code"]["output"], "implemented")
        self.assertEqual(store.messages[-1].channel, "stages")
        self.assertEqual(store.messages[-1].message_type, MessageType.STAGE_RESULT.value)
        self.assertEqual(store.checkpoints[-1][0], "stage:code")
        self.assertEqual(store.record.metadata["last_stage"], "code")
        self.assertEqual(store.record.metadata["shared_context"]["outputs"]["code"]["model"], "codex")

    def test_complete_and_fail_are_terminal_lifecycle_transitions(self) -> None:
        store = InMemorySessionStore()
        session = MultiModelSession(store.record, store)

        completed = session.complete("final answer", metadata={"actual_cost": 0.5})

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.metadata["execution_state"], "completed")
        self.assertEqual(completed.metadata["final_output"], "final answer")
        self.assertEqual(completed.metadata["actual_cost"], 0.5)
        self.assertEqual(store.checkpoints[-1][0], "complete")

        failed_store = InMemorySessionStore()
        failed_session = MultiModelSession(failed_store.record, failed_store)
        failed = failed_session.fail("boom", metadata={"run_mode": "simulate"})

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.metadata["execution_state"], "failed")
        self.assertEqual(failed.metadata["error"], "boom")
        self.assertEqual(failed_store.messages[-1].channel, "errors")
        self.assertEqual(failed_store.messages[-1].message_type, MessageType.ERROR.value)
        self.assertEqual(failed_store.checkpoints[-1][0], "failed")


class ExecutorStateMachineUnitTests(unittest.TestCase):
    def test_build_plan_applies_strategy_specific_state_transitions(self) -> None:
        registry = SimpleNamespace(config={"collaboration": {"swarm": {"default_workers": 2}}})
        executor = MultiModelExecutor(registry, router=Mock(), sessions=Mock())

        pair = executor.build_plan(
            "pair request",
            routing_decision(strategy=RoutingStrategy.PAIR_PROGRAMMING, models=["codex", "claude"]),
            context={"models": "local, codex"},
        )
        self.assertEqual([step.model for step in pair.steps], ["local", "codex"])
        self.assertEqual([step.kind for step in pair.steps], ["coder", "reviewer"])

        swarm = executor.build_plan(
            "swarm request",
            routing_decision(strategy=RoutingStrategy.SWARM, models=["codex", "claude"]),
            context={},
        )
        self.assertEqual([step.name for step in swarm.steps], ["split", "worker-1", "worker-2", "aggregate"])
        self.assertEqual(swarm.worker_count, 2)
        self.assertEqual(swarm.aggregator_model, "claude")

        pipeline = executor.build_plan(
            "pipeline request",
            routing_decision(strategy=RoutingStrategy.PIPELINE, models=["codex"], complexity=6),
            context={},
        )
        self.assertTrue(all(_condition_matches(step.condition, complexity=6) for step in pipeline.steps))

    def test_run_without_execute_stops_after_planned_state(self) -> None:
        decision = routing_decision(strategy=RoutingStrategy.SINGLE, models=["codex"])
        router = Mock(route=Mock(return_value=decision))
        sessions = Mock()
        store = InMemorySessionStore(session_record(status="planned"))
        sessions.create_session = Mock(return_value=store.record)
        sessions.get_session = Mock(side_effect=store.get_session)
        sessions.update_status = Mock(side_effect=store.update_status)
        executor = MultiModelExecutor(SimpleNamespace(config={}), router, sessions)

        with patch("tools.aegis_v2.executor.MultiModelSession", side_effect=lambda record, _sessions: MultiModelSession(record, store)), patch(
            "tools.aegis_v2.executor.RuntimeManager"
        ) as runtime_cls, patch("tools.aegis_v2.executor.pattern_for_strategy") as pattern_for_strategy:
            result = executor.run(" implement tests ", context={})

        self.assertFalse(result.executed)
        self.assertEqual(result.session.status, "planned")
        self.assertEqual(result.session.metadata["execution_state"], "phase1-foundation")
        self.assertEqual(store.checkpoints[0][0], "routed")
        runtime_cls.assert_not_called()
        pattern_for_strategy.assert_not_called()

    def test_run_with_execute_drives_running_then_completed_lifecycle(self) -> None:
        decision = routing_decision(strategy=RoutingStrategy.SINGLE, models=["codex"])
        router = Mock(route=Mock(return_value=decision))
        store = InMemorySessionStore(session_record(status="planned"))
        sessions = Mock()
        sessions.create_session = Mock(return_value=store.record)
        sessions.get_session = Mock(side_effect=store.get_session)
        registry = SimpleNamespace(config={})
        executor = MultiModelExecutor(registry, router, sessions)
        execution = PatternExecutionResult(
            strategy=RoutingStrategy.SINGLE,
            final_output="done",
            stage_results=[
                StageResult("single", "codex", "single", "done", 0, 3, approximate_cost=0.02),
            ],
            approximate_cost=0.02,
        )
        pattern = Mock()
        pattern.execute.return_value = execution
        runtime = SimpleNamespace(mode_label=Mock(return_value="simulate"), use_bridge=False)

        with patch("tools.aegis_v2.executor.MultiModelSession", side_effect=lambda record, _sessions: MultiModelSession(record, store)), patch(
            "tools.aegis_v2.executor.RuntimeManager", return_value=runtime
        ), patch("tools.aegis_v2.executor.pattern_for_strategy", return_value=pattern):
            result = executor.run("implement tests", context={"execute": True, "simulate": True})

        self.assertTrue(result.executed)
        self.assertEqual(result.session.status, "completed")
        self.assertEqual(result.session.metadata["execution_state"], "completed")
        self.assertEqual(result.session.metadata["final_output"], "done")
        self.assertEqual(result.session.metadata["actual_cost"], 0.02)
        self.assertEqual([status for status, _ in store.status_updates], ["running", "completed"])
        self.assertEqual(store.messages[0].message_type, "execution_start")
        pattern.execute.assert_called_once()

    def test_run_with_execute_marks_session_failed_when_pattern_raises(self) -> None:
        decision = routing_decision(strategy=RoutingStrategy.SINGLE, models=["codex"])
        router = Mock(route=Mock(return_value=decision))
        store = InMemorySessionStore(session_record(status="planned"))
        sessions = Mock()
        sessions.create_session = Mock(return_value=store.record)
        sessions.get_session = Mock(side_effect=store.get_session)
        executor = MultiModelExecutor(SimpleNamespace(config={}), router, sessions)
        pattern = Mock()
        pattern.execute.side_effect = RuntimeError("execution exploded")
        runtime = SimpleNamespace(mode_label=Mock(return_value="simulate"), use_bridge=False)

        with patch("tools.aegis_v2.executor.MultiModelSession", side_effect=lambda record, _sessions: MultiModelSession(record, store)), patch(
            "tools.aegis_v2.executor.RuntimeManager", return_value=runtime
        ), patch("tools.aegis_v2.executor.pattern_for_strategy", return_value=pattern):
            with self.assertRaises(RuntimeError):
                executor.run("implement tests", context={"execute": True, "simulate": True})

        self.assertEqual(store.record.status, "failed")
        self.assertEqual(store.record.metadata["execution_state"], "failed")
        self.assertEqual(store.record.metadata["error"], "execution exploded")
        self.assertEqual([status for status, _ in store.status_updates], ["running", "failed"])


if __name__ == "__main__":
    unittest.main()
