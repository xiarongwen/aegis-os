import json
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.aegis_v2.collaboration import MoAPattern, SwarmPattern, _parse_subtasks, _review_verdict
from tools.aegis_v2.config import build_paths
from tools.aegis_v2.executor import MultiModelExecutor
from tools.aegis_v2.registry import ModelRegistry
from tools.aegis_v2.router import TaskRouter
from tools.aegis_v2.runtime import RuntimeExecutionError, RuntimeManager
from tools.aegis_v2.session import MultiModelSession, SessionStore
from tools.aegis_v2.cli import render_run_result
from tools.aegis_v2.types import (
    ExecutionPlan,
    ExecutionStep,
    PatternExecutionResult,
    RoutingDecision,
    RoutingStrategy,
    RunResult,
    RuntimeResult,
    SessionRecord,
    StageResult,
    TaskType,
)


def init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "AEGIS Test"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "aegis@example.com"], check=True, capture_output=True, text=True)


class ParallelProbeRuntime:
    def __init__(self, registry: ModelRegistry, parallel_stages: list[str], *, group_size: int | None = None) -> None:
        self.registry = registry
        self.parallel_stages = set(parallel_stages)
        self.group_size = group_size or len(parallel_stages)
        self.barrier = threading.Barrier(self.group_size)
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.completed_in_group = 0

    def complete(
        self,
        model_name: str,
        prompt: str,
        *,
        session_id: str,
        stage_name: str,
        metadata: dict[str, object] | None = None,
    ) -> RuntimeResult:
        del session_id
        payload = dict(metadata or {})
        if stage_name == "split":
            output = "\n".join(f"{index + 1}. Subtask {index + 1}" for index in range(self.barrier.parties))
            return RuntimeResult(
                model=model_name,
                runtime="simulate",
                output=output,
                exit_code=0,
                duration_ms=0,
                command=["simulate", stage_name],
                log_path="",
                approximate_cost=0.0,
                metadata=payload,
            )
        if stage_name == "aggregate":
            return RuntimeResult(
                model=model_name,
                runtime="simulate",
                output=f"aggregated from {len(self.parallel_stages)} results",
                exit_code=0,
                duration_ms=0,
                command=["simulate", stage_name],
                log_path="",
                approximate_cost=0.0,
                metadata=payload,
            )
        if stage_name in self.parallel_stages:
            with self._lock:
                if self.completed_in_group >= self.group_size:
                    self.barrier = threading.Barrier(self.group_size)
                    self.completed_in_group = 0
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                self.barrier.wait(timeout=1.0)
                time.sleep(0.05)
            except threading.BrokenBarrierError as exc:
                raise AssertionError(f"{stage_name} did not run concurrently") from exc
            finally:
                with self._lock:
                    self.active -= 1
                    self.completed_in_group += 1
            return RuntimeResult(
                model=model_name,
                runtime="simulate",
                output=f"{stage_name} output",
                exit_code=0,
                duration_ms=50,
                command=["simulate", stage_name],
                log_path="",
                approximate_cost=0.01,
                metadata=payload,
            )
        return RuntimeResult(
            model=model_name,
            runtime="simulate",
            output=f"{stage_name} output",
            exit_code=0,
            duration_ms=0,
            command=["simulate", stage_name],
            log_path="",
            approximate_cost=0.0,
            metadata=payload,
        )


class PairStagnationRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(
        self,
        model_name: str,
        prompt: str,
        *,
        session_id: str,
        stage_name: str,
        metadata: dict[str, object] | None = None,
    ) -> RuntimeResult:
        del model_name, prompt, session_id
        self.calls.append(stage_name)
        payload = dict(metadata or {})
        if stage_name.startswith("code-round"):
            output = "same implementation"
        else:
            output = "REVISE\nNeed stronger tests."
        return RuntimeResult(
            model="simulate",
            runtime="simulate",
            output=output,
            exit_code=0,
            duration_ms=1,
            command=["simulate", stage_name],
            log_path="",
            approximate_cost=0.01,
            metadata=payload,
        )


class StubPopen:
    def __init__(self, command: list[str], *, stdout_text: str = "", stderr_text: str = "", returncode: int = 0) -> None:
        self.command = command
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self._returncode = returncode

    def poll(self) -> int | None:
        if self.stdout.tell() == len(self.stdout.getvalue()) and self.stderr.tell() == len(self.stderr.getvalue()):
            return self._returncode
        return None

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self._returncode

    def kill(self) -> None:
        self._returncode = -9


class AegisV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-v2-workspace-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(self.workspace_dir)})
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def run_aegis(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["AEGIS_WORKSPACE_ROOT"] = str(self.workspace_dir)
        return subprocess.run(
            ["bash", str(Path(__file__).resolve().parents[1] / "aegis"), *args],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def make_registry(self) -> ModelRegistry:
        registry = ModelRegistry.from_workspace(build_paths(self.workspace_dir))
        registry.config.setdefault("performance", {})
        return registry

    def make_session(self, *, request: str, strategy: RoutingStrategy, models: list[str]) -> MultiModelSession:
        paths = build_paths(self.workspace_dir)
        sessions = SessionStore(paths)
        decision = RoutingDecision(
            task_type=TaskType.CODE_REVIEW,
            strategy=strategy,
            models=models,
            mode="balanced",
            complexity=6,
            estimated_cost=0.2,
            estimated_time_seconds=10,
        )
        record = sessions.create_session(request=request, decision=decision, metadata={"estimated_cost": 0.2})
        return MultiModelSession(record, sessions)

    def test_router_dry_run_prefers_quality_architecture_model(self) -> None:
        completed = self.run_aegis("router", "dry-run", "设计并重构用户权限系统架构", "--mode", "quality", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["task_type"], "architecture")
        self.assertEqual(payload["strategy"], "moa")
        self.assertGreaterEqual(len(payload["models"]), 2)

    def test_run_creates_session_and_pipeline_plan(self) -> None:
        completed = self.run_aegis("run", "修复登录功能里的 SQL 注入 bug", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["routing"]["task_type"], "debugging")
        self.assertEqual(payload["routing"]["strategy"], "pipeline")
        self.assertEqual(payload["session"]["status"], "planned")
        self.assertTrue((self.workspace_dir / ".aegis" / "state" / "sessions.db").exists())

        session_id = payload["session"]["session_id"]
        show_completed = self.run_aegis("session", "show", session_id, "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        show_payload = json.loads(show_completed.stdout)
        self.assertEqual(show_payload["session_id"], session_id)
        self.assertEqual(show_payload["checkpoints"][0]["stage"], "routed")
        self.assertEqual(show_payload["messages"], [])

    def test_top_level_pair_command_forces_pair_strategy(self) -> None:
        completed = self.run_aegis("pair", "重构认证模块并保持行为不变", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["routing"]["strategy"], "pair")
        self.assertEqual(payload["plan"]["steps"][0]["kind"], "coder")

    def test_legacy_collaboration_command_is_no_longer_exposed(self) -> None:
        completed = self.run_aegis("collaboration", "pair", "重构认证模块并保持行为不变", "--format", "json")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unrecognized arguments", completed.stdout or completed.stderr)

    def test_config_init_materializes_v2_defaults(self) -> None:
        completed = self.run_aegis("config", "init", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        written = payload["written"]
        self.assertEqual(len(written), 2)
        self.assertTrue((self.workspace_dir / ".aegis" / "config.yml").exists())
        self.assertTrue((self.workspace_dir / ".aegis" / "models" / "registry.yml").exists())

    def test_registry_and_sessions_work_without_materialized_config(self) -> None:
        paths = build_paths(self.workspace_dir)
        registry = ModelRegistry.from_workspace(paths)
        router = TaskRouter(registry)
        sessions = SessionStore(paths)
        decision = router.route("写一个新的待办事项功能")
        record = sessions.create_session(
            request="写一个新的待办事项功能",
            decision=decision,
            metadata={"estimated_cost": decision.estimated_cost},
        )
        self.assertEqual(record.task_type, "code_gen")
        self.assertGreaterEqual(len(sessions.list_sessions()), 1)

    def test_execute_simulated_pipeline_records_messages(self) -> None:
        completed = self.run_aegis(
            "run",
            "修复登录功能里的 SQL 注入 bug",
            "--execute",
            "--simulate",
            "--format",
            "json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["executed"])
        self.assertEqual(payload["session"]["status"], "completed")
        self.assertEqual(payload["execution"]["strategy"], "pipeline")
        self.assertGreaterEqual(len(payload["execution"]["stage_results"]), 3)

        session_id = payload["session"]["session_id"]
        show_completed = self.run_aegis("session", "show", session_id, "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        show_payload = json.loads(show_completed.stdout)
        self.assertGreaterEqual(len(show_payload["messages"]), 3)
        self.assertEqual(show_payload["checkpoints"][-1]["stage"], "complete")
        self.assertEqual(show_payload["metadata"]["execution_state"], "completed")

    def test_simulate_flag_executes_without_explicit_execute(self) -> None:
        completed = self.run_aegis(
            "run",
            "修复登录功能里的 SQL 注入 bug",
            "--simulate",
            "--format",
            "json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["executed"])
        self.assertEqual(payload["session"]["status"], "completed")
        self.assertEqual(payload["session"]["metadata"]["run_mode"], "simulate")

    def test_execute_simulated_pair_records_review_feedback(self) -> None:
        completed = self.run_aegis(
            "pair",
            "重构认证模块并保持行为不变",
            "--execute",
            "--simulate",
            "--format",
            "json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["executed"])
        self.assertEqual(payload["execution"]["strategy"], "pair")
        self.assertGreaterEqual(len(payload["execution"]["stage_results"]), 2)
        self.assertGreaterEqual(payload["execution"]["iterations"], 1)

    def test_pair_pattern_stops_after_stagnant_feedback(self) -> None:
        session = self.make_session(
            request="重构认证模块并保持行为不变",
            strategy=RoutingStrategy.PAIR_PROGRAMMING,
            models=["codex", "claude-sonnet-4-6"],
        )
        plan = ExecutionPlan(
            strategy=RoutingStrategy.PAIR_PROGRAMMING,
            max_iterations=5,
            steps=[
                ExecutionStep(name="code", model="codex", kind="coder", prompt="implement"),
                ExecutionStep(name="review", model="claude-sonnet-4-6", kind="reviewer", prompt="review"),
            ],
        )
        runtime = PairStagnationRuntime()

        from tools.aegis_v2.collaboration import PairProgrammingPattern

        result = PairProgrammingPattern().execute(
            request="重构认证模块并保持行为不变",
            plan=plan,
            runtime=runtime,
            session=session,
        )

        self.assertEqual(result.iterations, 3)
        self.assertEqual(session.shared_context.get("pair_stop_reason"), "stagnated_after_repeated_feedback")

    def test_review_verdict_only_uses_first_non_empty_line(self) -> None:
        self.assertEqual(_review_verdict("APPROVED\nAll good."), "APPROVED")
        self.assertEqual(_review_verdict("Looks fine\nAPPROVED"), "REVISE")
        self.assertEqual(_review_verdict("\nBLOCKED\nNeeds migration"), "BLOCKED")

    def test_session_resume_replays_request_with_original_context(self) -> None:
        initial = self.run_aegis("pair", "重构认证模块并保持行为不变", "--budget", "2.5", "--execute", "--simulate", "--format", "json")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        initial_payload = json.loads(initial.stdout)

        resumed = self.run_aegis(
            "session",
            "resume",
            initial_payload["session"]["session_id"],
            "--format",
            "json",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        resumed_payload = json.loads(resumed.stdout)
        self.assertTrue(resumed_payload["executed"])
        self.assertEqual(resumed_payload["routing"]["strategy"], "pair")
        self.assertEqual(resumed_payload["session"]["metadata"]["budget"], 2.5)
        self.assertEqual(
            resumed_payload["session"]["metadata"]["resumed_from"],
            initial_payload["session"]["session_id"],
        )

    def test_session_recover_can_override_strategy_and_track_source(self) -> None:
        initial = self.run_aegis("run", "修复登录功能里的 SQL 注入 bug", "--execute", "--simulate", "--format", "json")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        initial_payload = json.loads(initial.stdout)

        recovered = self.run_aegis(
            "session",
            "recover",
            initial_payload["session"]["session_id"],
            "--strategy",
            "swarm",
            "--models",
            "codex,claude-sonnet-4-6",
            "--format",
            "json",
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        recovered_payload = json.loads(recovered.stdout)
        self.assertTrue(recovered_payload["executed"])
        self.assertEqual(recovered_payload["routing"]["strategy"], "swarm")
        self.assertEqual(recovered_payload["routing"]["models"], ["codex", "claude-sonnet-4-6"])
        self.assertEqual(
            recovered_payload["session"]["metadata"]["recovered_from"],
            initial_payload["session"]["session_id"],
        )

    def test_empty_request_returns_validation_error(self) -> None:
        completed = self.run_aegis("run", "", "--format", "json")
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertIn("request cannot be empty", payload["error"])

    def test_router_uses_moa_for_high_complexity_code_review(self) -> None:
        completed = self.run_aegis(
            "router",
            "dry-run",
            "请从安全、性能、可维护性多个角度深度评审这个复杂认证重构方案并比较取舍",
            "--format",
            "json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["strategy"], "moa")
        self.assertGreaterEqual(len(payload["models"]), 2)

    def test_router_accepts_agentic_classifier_override(self) -> None:
        registry = self.make_registry()
        router = TaskRouter(
            registry,
            classifier=lambda request, context: {
                "task_type": "research",
                "strategy": "moa",
                "models": ["codex", "claude-sonnet-4-6", "claude-opus-4-7"],
                "rationale": ["agentic advisor selected research moa"],
            },
        )

        decision = router.route("去看看今天的黄金行情")

        self.assertEqual(decision.task_type.value, "research")
        self.assertEqual(decision.strategy.value, "moa")
        self.assertGreaterEqual(len(decision.models), 2)
        self.assertIsNotNone(decision.advisor)
        assert decision.advisor is not None
        self.assertEqual(decision.advisor["task_type"], "research")
        self.assertIn("advisor:", " ".join(decision.rationale))

    def test_explicit_swarm_models_are_respected_in_execution_plan(self) -> None:
        completed = self.run_aegis("swarm", "生成认证模块测试用例", "--models", "local-llm", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["routing"]["models"], ["local-llm"])
        self.assertEqual(
            [step["model"] for step in payload["plan"]["steps"]],
            ["local-llm", "local-llm", "local-llm"],
        )

    def test_moa_plan_uses_last_model_as_independent_aggregator(self) -> None:
        registry = self.make_registry()
        router = TaskRouter(registry)
        sessions = SessionStore(build_paths(self.workspace_dir))
        executor = MultiModelExecutor(registry, router, sessions)
        decision = RoutingDecision(
            task_type=TaskType.CODE_REVIEW,
            strategy=RoutingStrategy.MOA,
            models=["codex", "claude-sonnet-4-6", "claude-opus-4-7"],
            mode="balanced",
            complexity=8,
            estimated_cost=0.3,
            estimated_time_seconds=120,
        )

        plan = executor.build_plan("从多个专家角度评审方案", decision)

        self.assertEqual(plan.aggregator_model, "claude-opus-4-7")
        self.assertEqual([step.model for step in plan.steps], ["codex", "claude-sonnet-4-6", "claude-opus-4-7"])
        self.assertEqual([step.kind for step in plan.steps], ["expert", "expert", "aggregator"])
        self.assertTrue(plan.steps[0].name.startswith("expert-"))
        self.assertIn("Role:", plan.steps[0].prompt)
        self.assertIn("Focus:", plan.steps[0].prompt)

    def test_budget_flag_is_persisted_in_session_metadata(self) -> None:
        completed = self.run_aegis("run", "实现登录接口", "--budget", "3.5", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["session"]["metadata"]["budget"], 3.5)

    def test_models_test_marks_cli_runtime_available_when_binary_exists(self) -> None:
        completed = self.run_aegis("models", "test", "codex", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["available"])
        self.assertIn("binary=codex:ok", payload["details"])

    def test_runtime_retries_codex_with_workspace_scoped_home_after_session_error(self) -> None:
        registry = self.make_registry()
        manager = RuntimeManager(registry)
        fake_home = self.workspace_dir / "fake-home"
        source_auth = fake_home / ".codex" / "auth.json"
        source_auth.parent.mkdir(parents=True, exist_ok=True)
        source_auth.write_text('{"token":"test"}\n', encoding="utf-8")
        source_config = fake_home / ".codex" / "config.toml"
        source_config.write_text('model = "gpt-5.4"\n', encoding="utf-8")

        with patch.dict(os.environ, {"HOME": str(fake_home)}, clear=False), patch.object(
            manager.registry,
            "check_model",
            return_value=type("Health", (), {"available": True, "details": "binary=codex:ok"})(),
        ), patch("tools.aegis_v2.runtime.resolve_runtime_binary", return_value="/opt/mock/bin/codex"), patch(
            "tools.aegis_v2.runtime.subprocess.Popen"
        ) as mock_popen:
            mock_popen.side_effect = [
                StubPopen(
                    ["/opt/mock/bin/codex"],
                    stderr_text="Fatal error: Codex cannot access session files at /tmp/.codex/sessions (permission denied)\n",
                    returncode=1,
                ),
                StubPopen(
                    ["/opt/mock/bin/codex"],
                    stdout_text="ok\n",
                    returncode=0,
                ),
            ]
            result = manager.complete(
                "codex",
                "输出一句 hello",
                session_id="sess-test",
                stage_name="single",
                metadata={"kind": "single"},
            )

        self.assertEqual(result.exit_code, 0)
        first_call = mock_popen.call_args_list[0]
        second_call = mock_popen.call_args_list[1]
        self.assertEqual(first_call.args[0][0], "/opt/mock/bin/codex")
        self.assertNotIn("CODEX_HOME", first_call.kwargs["env"])
        self.assertEqual(second_call.args[0][0], "/opt/mock/bin/codex")
        self.assertEqual(
            Path(second_call.kwargs["env"]["CODEX_HOME"]).resolve(),
            (self.workspace_dir / ".aegis" / "runtime-home" / "codex").resolve(),
        )
        mirrored_auth = (self.workspace_dir / ".aegis" / "runtime-home" / "codex" / "auth.json").resolve()
        self.assertTrue(mirrored_auth.exists())
        self.assertEqual(mirrored_auth.read_text(encoding="utf-8"), '{"token":"test"}\n')
        mirrored_config = (self.workspace_dir / ".aegis" / "runtime-home" / "codex" / "config.toml").resolve()
        self.assertTrue(mirrored_config.exists())
        self.assertEqual(mirrored_config.read_text(encoding="utf-8"), 'model = "gpt-5.4"\n')

    def test_runtime_failure_reports_usage_limit_instead_of_generic_login_hint(self) -> None:
        registry = self.make_registry()
        manager = RuntimeManager(registry)

        with patch.object(
            manager.registry,
            "check_model",
            return_value=type("Health", (), {"available": True, "details": "binary=codex:ok"})(),
        ), patch.object(
            manager,
            "_ranked_fallback_candidates",
            return_value=[],
        ), patch(
            "tools.aegis_v2.runtime._extract_failure_reason",
            return_value="usage limit reached for the current Codex account",
        ), patch("tools.aegis_v2.runtime.resolve_runtime_binary", return_value="/opt/mock/bin/codex"), patch(
            "tools.aegis_v2.runtime.subprocess.Popen"
        ) as mock_popen:
            mock_popen.return_value = StubPopen(
                ["/opt/mock/bin/codex"],
                stderr_text="ERROR: You've hit your usage limit. Purchase more credits and try again later.\n",
                returncode=1,
            )
            with self.assertRaises(RuntimeExecutionError) as ctx:
                manager.complete(
                    "codex",
                    "输出一句 hello",
                    session_id="sess-test",
                    stage_name="single",
                    metadata={"kind": "single"},
                )

        self.assertIn("usage limit reached", str(ctx.exception))
        self.assertNotIn("Cause: ERROR: You've hit your usage limit", str(ctx.exception))

    def test_runtime_falls_back_to_available_model(self) -> None:
        registry = self.make_registry()
        manager = RuntimeManager(registry)

        def fake_execute_once(spec, prompt, *, session_id, stage_name, payload):
            del prompt, session_id, stage_name
            return RuntimeResult(
                model=spec.name,
                runtime=spec.runtime,
                output="fallback output",
                exit_code=0,
                duration_ms=1,
                command=["fake", spec.name],
                log_path="",
                approximate_cost=0.01,
                metadata=payload,
            )

        with patch.object(manager.registry, "check_model") as check_model, patch.object(
            manager, "_execute_once", side_effect=fake_execute_once
        ):
            def health_for(name: str):
                class Health:
                    def __init__(self, available: bool, details: str) -> None:
                        self.available = available
                        self.details = details
                if name == "local-llm":
                    return Health(False, "binary=ollama:missing")
                return Health(True, "binary ok")

            check_model.side_effect = health_for
            result = manager.complete(
                "local-llm",
                "review code",
                session_id="sess-test",
                stage_name="review",
                metadata={"kind": "expert"},
            )

        self.assertEqual(result.model, "claude-opus-4-7")
        self.assertEqual(result.metadata["fallback_from"], "local-llm")
        self.assertEqual(result.metadata["fallback_to"], "claude-opus-4-7")

    def test_runtime_retries_before_succeeding(self) -> None:
        registry = self.make_registry()
        manager = RuntimeManager(registry)
        calls = {"count": 0}

        def flaky_execute(spec, prompt, *, session_id, stage_name, payload):
            del spec, prompt, session_id, stage_name
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeExecutionError("temporary failure", model_name="codex", stage_name="code")
            return RuntimeResult(
                model="codex",
                runtime="codex-cli",
                output="ok after retry",
                exit_code=0,
                duration_ms=1,
                command=["fake", "codex"],
                log_path="",
                approximate_cost=0.01,
                metadata=payload,
            )

        with patch.object(manager, "_execute_once", side_effect=flaky_execute):
            result = manager.complete(
                "codex",
                "implement task",
                session_id="sess-test",
                stage_name="code",
                metadata={"kind": "coder"},
            )

        self.assertEqual(calls["count"], 2)
        self.assertEqual(result.metadata["attempt"], 2)
        self.assertFalse(result.metadata["retrying"])

    def test_swarm_pattern_executes_workers_in_parallel(self) -> None:
        registry = self.make_registry()
        registry.config["performance"]["parallel_execution"] = True
        registry.config["performance"]["max_concurrent_models"] = 3
        runtime = ParallelProbeRuntime(registry, ["worker-1", "worker-2", "worker-3"])
        session = self.make_session(
            request="并行审查三个模块",
            strategy=RoutingStrategy.SWARM,
            models=["codex", "codex", "codex"],
        )
        plan = ExecutionPlan(
            strategy=RoutingStrategy.SWARM,
            worker_count=3,
            aggregator_model="claude-opus-4-7",
            steps=[
                ExecutionStep(name="split", model="claude-opus-4-7", kind="splitter", prompt="split request"),
                ExecutionStep(name="worker-1", model="codex", kind="worker", prompt="review worker 1"),
                ExecutionStep(name="worker-2", model="codex", kind="worker", prompt="review worker 2"),
                ExecutionStep(name="worker-3", model="codex", kind="worker", prompt="review worker 3"),
                ExecutionStep(name="aggregate", model="claude-opus-4-7", kind="aggregator", prompt="merge results"),
            ],
        )

        result = SwarmPattern().execute(
            request="并行审查三个模块",
            plan=plan,
            runtime=runtime,
            session=session,
        )

        self.assertEqual(result.final_output, "aggregated from 3 results")
        self.assertEqual(
            [stage.stage_name for stage in result.stage_results],
            ["split", "worker-1", "worker-2", "worker-3", "aggregate"],
        )
        self.assertEqual(runtime.max_active, 3)
        self.assertEqual(session.shared_context.get("swarm_subtasks"), ["Subtask 1", "Subtask 2", "Subtask 3"])

    def test_moa_pattern_executes_experts_in_parallel(self) -> None:
        registry = self.make_registry()
        registry.config["performance"]["parallel_execution"] = True
        registry.config["performance"]["max_concurrent_models"] = 3
        runtime = ParallelProbeRuntime(
            registry,
            [
                "expert-correctness",
                "expert-risk",
                "expert-maintainability",
                "expert-correctness-deliberate",
                "expert-risk-deliberate",
                "expert-maintainability-deliberate",
            ],
            group_size=3,
        )
        session = self.make_session(
            request="从三个专家角度评审方案",
            strategy=RoutingStrategy.MOA,
            models=["codex", "claude-sonnet-4-6", "claude-opus-4-7"],
        )
        plan = ExecutionPlan(
            strategy=RoutingStrategy.MOA,
            aggregator_model="claude-opus-4-7",
            steps=[
                ExecutionStep(name="expert-correctness", model="codex", kind="expert", prompt="Role: correctness\nFocus: validate correctness"),
                ExecutionStep(name="expert-risk", model="claude-sonnet-4-6", kind="expert", prompt="Role: risk\nFocus: find risks"),
                ExecutionStep(name="expert-maintainability", model="claude-opus-4-7", kind="expert", prompt="Role: maintainability\nFocus: judge maintainability"),
                ExecutionStep(name="aggregate", model="claude-opus-4-7", kind="aggregator", prompt="synthesize"),
            ],
        )

        result = MoAPattern().execute(
            request="从三个专家角度评审方案",
            plan=plan,
            runtime=runtime,
            session=session,
        )

        self.assertEqual(result.final_output, "aggregated from 6 results")
        self.assertEqual(
            [stage.stage_name for stage in result.stage_results],
            [
                "expert-correctness",
                "expert-risk",
                "expert-maintainability",
                "expert-correctness-deliberate",
                "expert-risk-deliberate",
                "expert-maintainability-deliberate",
                "aggregate",
            ],
        )
        self.assertEqual(runtime.max_active, 3)
        findings = session.shared_context.get("moa_expert_findings")
        self.assertEqual(len(findings), 6)
        self.assertEqual(findings[0]["role"], "correctness")

    def test_render_run_result_planned_session_contains_key_info(self) -> None:
        result = RunResult(
            session=SessionRecord(
                session_id="sess-test-123",
                request="fix bug",
                task_type="debugging",
                strategy="pipeline",
                models=["codex"],
                mode="balanced",
                status="planned",
                metadata={},
                created_at="2026-04-23T10:00:00Z",
                updated_at="2026-04-23T10:00:00Z",
            ),
            routing=RoutingDecision(
                task_type=TaskType.DEBUGGING,
                strategy=RoutingStrategy.PIPELINE,
                models=["codex"],
                mode="balanced",
                complexity=5,
                estimated_cost=0.12,
                estimated_time_seconds=90,
            ),
            plan=ExecutionPlan(
                strategy=RoutingStrategy.PIPELINE,
                steps=[
                    ExecutionStep(name="analyze", model="codex", kind="stage", prompt="p1"),
                    ExecutionStep(name="fix", model="codex", kind="stage", prompt="p2"),
                ],
            ),
            executed=False,
            message="Ready to run.",
        )
        text = render_run_result(result)
        self.assertIn("sess-test-123", text)
        self.assertIn("debugging", text)
        self.assertIn("pipeline", text)
        self.assertIn("codex", text)
        self.assertIn("5/10", text)
        self.assertIn("$0.12", text)
        self.assertIn("90s", text)
        self.assertIn("analyze", text)
        self.assertIn("fix", text)
        self.assertIn("Ready to run.", text)

    def test_render_run_result_executed_session_shows_stages_and_cost(self) -> None:
        result = RunResult(
            session=SessionRecord(
                session_id="sess-exec-456",
                request="refactor auth",
                task_type="refactoring",
                strategy="pair",
                models=["codex", "claude-sonnet-4-6"],
                mode="balanced",
                status="completed",
                metadata={},
                created_at="2026-04-23T10:00:00Z",
                updated_at="2026-04-23T10:00:00Z",
            ),
            routing=RoutingDecision(
                task_type=TaskType.REFACTORING,
                strategy=RoutingStrategy.PAIR_PROGRAMMING,
                models=["codex", "claude-sonnet-4-6"],
                mode="balanced",
                complexity=4,
                estimated_cost=0.08,
                estimated_time_seconds=60,
            ),
            plan=ExecutionPlan(
                strategy=RoutingStrategy.PAIR_PROGRAMMING,
                steps=[
                    ExecutionStep(name="code", model="codex", kind="coder", prompt="p1"),
                    ExecutionStep(name="review", model="claude-sonnet-4-6", kind="reviewer", prompt="p2"),
                ],
            ),
            executed=True,
            message="Done.",
            execution=PatternExecutionResult(
                strategy=RoutingStrategy.PAIR_PROGRAMMING,
                final_output="final code here",
                stage_results=[
                    StageResult(
                        stage_name="code",
                        model="codex",
                        kind="coder",
                        output="code output",
                        exit_code=0,
                        duration_ms=1200,
                        approximate_cost=0.001,
                    ),
                    StageResult(
                        stage_name="review",
                        model="claude-sonnet-4-6",
                        kind="reviewer",
                        output="LGTM",
                        exit_code=0,
                        duration_ms=800,
                        approximate_cost=0.002,
                    ),
                ],
                iterations=2,
                approximate_cost=0.003,
            ),
        )
        text = render_run_result(result)
        self.assertIn("sess-exec-456", text)
        self.assertIn("completed", text)
        self.assertIn("code", text)
        self.assertIn("review", text)
        self.assertIn("$0.003", text)
        self.assertIn("1200ms", text)
        self.assertIn("800ms", text)
        self.assertIn("Iterations", text)
        self.assertIn("2", text)
        self.assertIn("final code here", text)
        self.assertIn("Done.", text)

    def test_render_run_result_respects_no_color(self) -> None:
        result = RunResult(
            session=SessionRecord(
                session_id="sess-color-789",
                request="test",
                task_type="code_gen",
                strategy="single",
                models=["codex"],
                mode="speed",
                status="planned",
                metadata={},
                created_at="2026-04-23T10:00:00Z",
                updated_at="2026-04-23T10:00:00Z",
            ),
            routing=RoutingDecision(
                task_type=TaskType.CODE_GENERATION,
                strategy=RoutingStrategy.SINGLE,
                models=["codex"],
                mode="speed",
                complexity=3,
                estimated_cost=0.01,
                estimated_time_seconds=30,
            ),
            plan=ExecutionPlan(strategy=RoutingStrategy.SINGLE, steps=[ExecutionStep(name="single", model="codex", kind="single", prompt="p")]),
            executed=False,
            message="Ready.",
        )
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            text = render_run_result(result)
        self.assertNotIn("\033[", text)
        self.assertIn("sess-color-789", text)

    def test_render_run_result_failed_stage_shows_error_icon(self) -> None:
        result = RunResult(
            session=SessionRecord(
                session_id="sess-fail-000",
                request="test",
                task_type="code_gen",
                strategy="single",
                models=["codex"],
                mode="speed",
                status="failed",
                metadata={},
                created_at="2026-04-23T10:00:00Z",
                updated_at="2026-04-23T10:00:00Z",
            ),
            routing=RoutingDecision(
                task_type=TaskType.CODE_GENERATION,
                strategy=RoutingStrategy.SINGLE,
                models=["codex"],
                mode="speed",
                complexity=3,
                estimated_cost=0.01,
                estimated_time_seconds=30,
            ),
            plan=ExecutionPlan(strategy=RoutingStrategy.SINGLE, steps=[ExecutionStep(name="build", model="codex", kind="single", prompt="p")]),
            executed=True,
            message="Failed.",
            execution=PatternExecutionResult(
                strategy=RoutingStrategy.SINGLE,
                final_output="",
                stage_results=[
                    StageResult(
                        stage_name="build",
                        model="codex",
                        kind="single",
                        output="error",
                        exit_code=1,
                        duration_ms=0,
                        approximate_cost=0.0,
                    ),
                ],
            ),
        )
        text = render_run_result(result)
        self.assertIn("failed", text)
        self.assertIn("build", text)
        self.assertIn("Failed.", text)

    def test_parse_subtasks_markdown_bullets(self) -> None:
        output = "- First task\n- Second task\n- Third task"
        result = _parse_subtasks(output, 3, "request")
        self.assertEqual(result, ["First task", "Second task", "Third task"])

    def test_parse_subtasks_numbered_lists(self) -> None:
        output = "1. First task\n2. Second task\n3) Third task\n(4) Fourth task"
        result = _parse_subtasks(output, 4, "request")
        self.assertEqual(result, ["First task", "Second task", "Third task", "Fourth task"])

    def test_parse_subtasks_json_array(self) -> None:
        output = '["Task A", "Task B", "Task C"]'
        result = _parse_subtasks(output, 3, "request")
        self.assertEqual(result, ["Task A", "Task B", "Task C"])

    def test_parse_subtasks_checkbox_items(self) -> None:
        output = "- [ ] First task\n- [x] Second task\n* [X] Third task"
        result = _parse_subtasks(output, 3, "request")
        self.assertEqual(result, ["First task", "Second task", "Third task"])

    def test_parse_subtasks_filters_headings(self) -> None:
        output = "Subtasks:\n- First task\nTasks:\n- Second task\nHere are the results:\n- Third task"
        result = _parse_subtasks(output, 3, "request")
        self.assertEqual(result, ["First task", "Second task", "Third task"])

    def test_parse_subtasks_deduplicates_items(self) -> None:
        output = "- First task\n- First task\n- second task\n- Second task"
        result = _parse_subtasks(output, 2, "request")
        self.assertEqual(result, ["First task", "second task"])

    def test_parse_subtasks_fills_defaults_when_short(self) -> None:
        output = "- Only one"
        result = _parse_subtasks(output, 3, "original request")
        self.assertEqual(result[0], "Only one")
        self.assertTrue(result[1].startswith("Subtask 2"))
        self.assertTrue(result[2].startswith("Subtask 3"))
        self.assertIn("original request", result[1])

    def test_parse_subtasks_mixed_formats(self) -> None:
        output = "1. Numbered task\n- Bullet task\n* [ ] Checkbox task\nPlain paragraph that is long enough to be considered"
        result = _parse_subtasks(output, 4, "request")
        self.assertEqual(result[0], "Numbered task")
        self.assertEqual(result[1], "Bullet task")
        self.assertEqual(result[2], "Checkbox task")
        self.assertIn("paragraph", result[3])

    def test_parse_subtasks_ignores_short_lines(self) -> None:
        output = "ok\n- Real task\nhi"
        result = _parse_subtasks(output, 1, "request")
        self.assertEqual(result[0], "Real task")

    def test_parse_subtasks_json_takes_precedence_over_markdown(self) -> None:
        output = '["JSON task 1", "JSON task 2"]\n- Markdown task\n1. Numbered task'
        result = _parse_subtasks(output, 2, "request")
        self.assertEqual(result, ["JSON task 1", "JSON task 2"])

    def test_tui_dashboard_renders_sessions_and_models(self) -> None:
        from io import StringIO
        from rich.console import Console
        from tools.aegis_v2.tui import render_dashboard

        paths = build_paths(self.workspace_dir)
        registry = ModelRegistry.from_workspace(paths)
        sessions = SessionStore(paths)

        # Create a session so dashboard has something to show
        router = TaskRouter(registry)
        decision = router.route("fix login bug")
        sessions.create_session(request="fix login bug", decision=decision, metadata={"estimated_cost": 0.05})

        dashboard = render_dashboard(sessions, registry)
        console = Console(file=StringIO(), width=120, record=True)
        console.print(dashboard)
        text = console.export_text()

        self.assertIn("AEGIS v2", text)
        self.assertIn("fix login bug", text)
        self.assertIn("最近会话", text)
        self.assertIn("主输入框", text)

    def test_tui_watch_renders_session_details(self) -> None:
        from io import StringIO
        from rich.console import Console
        from tools.aegis_v2.tui import render_watch

        paths = build_paths(self.workspace_dir)
        registry = ModelRegistry.from_workspace(paths)
        sessions = SessionStore(paths)
        router = TaskRouter(registry)
        decision = router.route("refactor auth module")
        session = sessions.create_session(request="refactor auth module", decision=decision, metadata={"estimated_cost": 0.08})

        watch = render_watch(sessions, session.session_id)
        console = Console(file=StringIO(), width=120, record=True)
        console.print(watch)
        text = console.export_text()

        self.assertIn("AEGIS v2", text)
        self.assertIn(session.session_id, text)
        self.assertIn("refactor auth module", text)
        self.assertIn("pair", text)
        self.assertIn("阶段", text)

    def test_tui_watch_shows_error_for_missing_session(self) -> None:
        from io import StringIO
        from rich.console import Console
        from tools.aegis_v2.tui import render_watch

        paths = build_paths(self.workspace_dir)
        sessions = SessionStore(paths)

        watch = render_watch(sessions, "sess-does-not-exist")
        console = Console(file=StringIO(), width=120, record=True)
        console.print(watch)
        text = console.export_text()

        self.assertIn("Session not found", text)
        self.assertIn("sess-does-not-exist", text)

    def test_tui_watch_shows_messages_and_checkpoints(self) -> None:
        from io import StringIO
        from rich.console import Console
        from tools.aegis_v2.tui import render_watch

        paths = build_paths(self.workspace_dir)
        registry = ModelRegistry.from_workspace(paths)
        sessions = SessionStore(paths)
        router = TaskRouter(registry)
        decision = router.route("generate tests")
        session = sessions.create_session(request="generate tests", decision=decision, metadata={"estimated_cost": 0.04})

        # Add a checkpoint
        sessions.add_checkpoint(session.session_id, "routed", {"plan": {}})
        # Add a message
        sessions.add_message(
            session_id=session.session_id,
            channel="lifecycle",
            sender="router",
            message_type="stage_start",
            content="starting code generation",
        )

        watch = render_watch(sessions, session.session_id)
        console = Console(file=StringIO(), width=120, record=True)
        console.print(watch)
        text = console.export_text()

        self.assertIn("消息", text)
        self.assertIn("lifecycle", text)
        self.assertIn("router", text)
        self.assertIn("starting code generation", text)

    def test_tui_task_input_creates_planned_session(self) -> None:
        from tools.aegis_v2.tui import TuiState, _submit_input

        paths = build_paths(self.workspace_dir)
        registry = ModelRegistry.from_workspace(paths)
        sessions = SessionStore(paths)
        state = TuiState(input_buffer="fix login bug")

        _submit_input(sessions, registry, state)

        records = sessions.list_sessions()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].request, "fix login bug")
        self.assertEqual(records[0].status, "planned")
        self.assertEqual(state.view, "watch")
        self.assertEqual(state.selected_session_id, records[0].session_id)

    def test_tui_models_command_switches_view(self) -> None:
        from tools.aegis_v2.tui import TuiState, _submit_input

        paths = build_paths(self.workspace_dir)
        registry = ModelRegistry.from_workspace(paths)
        sessions = SessionStore(paths)
        state = TuiState(input_buffer="/models")

        _submit_input(sessions, registry, state)

        self.assertEqual(state.view, "models")
