import json
import os
import shutil
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from rich.console import Console

from tools.aegis_1.cockpit import render_rich_cockpit
from tools.aegis_1.config import build_paths
from tools.aegis_1.engine import CollaborationEngine
from tools.aegis_1.planner import RunPlanner
from tools.aegis_1.policy import PolicyViolation
from tools.aegis_1.router import IntentRouter
from tools.aegis_1.session import SessionStore
from tools.aegis_1.types import RunStep


def init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "AEGIS Test"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "aegis@example.com"], check=True, capture_output=True, text=True)


class Aegis1CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-1-workspace-"))
        init_git_workspace(self.workspace_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def run_aegis(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["AEGIS_WORKSPACE_ROOT"] = str(self.workspace_dir)
        return subprocess.run(
            ["bash", str(self.repo_root / "aegis"), "v1", *args],
            cwd=str(self.repo_root),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_bare_request_creates_1_0_session(self) -> None:
        completed = self.run_aegis("修复登录 bug", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["route"]["task_type"], "debugging")
        self.assertEqual(payload["route"]["strategy"], "pipeline")
        self.assertEqual(payload["session"]["status"], "planned")
        self.assertTrue(payload["session"]["session_id"].startswith("a1-"))
        self.assertTrue((self.workspace_dir / ".aegis" / "state" / "aegis1_sessions.db").exists())

    def test_ulw_defaults_to_simulated_autopilot_cockpit(self) -> None:
        completed = self.run_aegis("ulw", "修复登录 bug")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("AEGIS AUTOPILOT", completed.stdout)
        self.assertIn("completed", completed.stdout)
        self.assertIn("任务进展", completed.stdout)
        self.assertIn("S8", completed.stdout)
        self.assertIn("delivery", completed.stdout)
        self.assertIn("八大底层能力", completed.stdout)
        self.assertIn("双向共验证", completed.stdout)
        self.assertIn("方圆会议", completed.stdout)
        self.assertIn("自动复盘", completed.stdout)
        self.assertIn("七业大师协同在场", completed.stdout)
        self.assertIn("三层一致的共识层", completed.stdout)
        self.assertIn("十二铁律", completed.stdout)

    def test_session_show_and_watch_include_events(self) -> None:
        run_completed = self.run_aegis("run", "重构认证模块", "--simulate", "--format", "json")
        self.assertEqual(run_completed.returncode, 0, run_completed.stderr)
        session_id = json.loads(run_completed.stdout)["session"]["session_id"]

        show_completed = self.run_aegis("session", "show", session_id, "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        show_payload = json.loads(show_completed.stdout)
        self.assertEqual(show_payload["strategy"], "pair")
        self.assertTrue(any(event["event_type"] == "stage_result" for event in show_payload["events"]))

        watch_completed = self.run_aegis("watch", session_id)
        self.assertEqual(watch_completed.returncode, 0, watch_completed.stderr)
        self.assertIn(session_id, watch_completed.stdout)

    def test_pipeline_plan_has_eight_autopilot_stages(self) -> None:
        completed = self.run_aegis("pipeline", "修复登录 bug", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        kinds = [step["kind"] for step in payload["plan"]["steps"]]
        self.assertEqual(
            kinds,
            ["plan_check", "story_split", "spec", "build", "review", "verify", "done_gate", "delivery"],
        )
        self.assertEqual(payload["plan"]["steps"][0]["depends_on"], [])
        self.assertEqual(payload["plan"]["steps"][1]["depends_on"], ["S1"])
        self.assertEqual(payload["plan"]["steps"][7]["depends_on"], ["S7"])

    def test_swarm_plan_has_fan_out_and_fan_in_dependencies(self) -> None:
        completed = self.run_aegis("swarm", "为支付模块补测试", "--workers", "3", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        steps = payload["plan"]["steps"]
        self.assertEqual(steps[0]["kind"], "split")
        self.assertEqual([step["depends_on"] for step in steps[1:4]], [["S1"], ["S1"], ["S1"]])
        self.assertEqual(steps[4]["kind"], "aggregate")
        self.assertEqual(steps[4]["depends_on"], ["S2", "S3", "S4"])

    def test_scheduler_emits_dependency_events(self) -> None:
        completed = self.run_aegis("swarm", "为支付模块补测试", "--workers", "2", "--simulate", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        session_id = json.loads(completed.stdout)["session"]["session_id"]
        show_completed = self.run_aegis("session", "show", session_id, "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        events = json.loads(show_completed.stdout)["events"]
        self.assertTrue(any(event["event_type"] == "scheduler_plan" for event in events))
        ready_events = [event for event in events if event["event_type"] == "scheduler_ready"]
        self.assertTrue(any(event["metadata"]["ready"] == ["S1"] for event in ready_events))
        self.assertTrue(any(event["metadata"]["ready"] == ["S2", "S3"] for event in ready_events))
        aggregate = next(event for event in events if event["event_type"] == "stage_result" and event["stage_name"] == "S4")
        self.assertEqual(aggregate["metadata"]["depends_on"], ["S2", "S3"])

    def test_pair_execute_simulates_review_fix_loop(self) -> None:
        completed = self.run_aegis("pair", "重构认证模块", "--simulate", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        session_id = json.loads(completed.stdout)["session"]["session_id"]
        show_completed = self.run_aegis("session", "show", session_id, "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        events = json.loads(show_completed.stdout)["events"]
        self.assertTrue(any(event["event_type"] == "review_feedback" and event["metadata"].get("verdict") == "REVISE" for event in events))
        self.assertTrue(any(event["event_type"] == "retry" for event in events))
        self.assertTrue(any(event["event_type"] == "review_feedback" and event["metadata"].get("verdict") == "APPROVED" for event in events))

    def test_run_writes_artifacts_and_governance_events(self) -> None:
        completed = self.run_aegis("pipeline", "修复登录 bug", "--simulate", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        session_id = json.loads(completed.stdout)["session"]["session_id"]
        run_dir = self.workspace_dir / ".aegis" / "runs" / "aegis-1" / session_id
        self.assertTrue((run_dir / "run_manifest.json").exists())
        self.assertTrue((run_dir / "events.jsonl").exists())
        self.assertTrue((run_dir / "summary.md").exists())

        show_completed = self.run_aegis("session", "show", session_id, "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        events = json.loads(show_completed.stdout)["events"]
        event_types = {event["event_type"] for event in events}
        self.assertIn("persona", event_types)
        self.assertIn("council", event_types)
        self.assertIn("policy", event_types)
        self.assertIn("verification", event_types)
        self.assertIn("done_gate", event_types)
        self.assertIn("evolution", event_types)

    def test_watch_live_flag_is_available_for_completed_session(self) -> None:
        run_completed = self.run_aegis("run", "修复登录 bug", "--simulate", "--format", "json")
        self.assertEqual(run_completed.returncode, 0, run_completed.stderr)
        session_id = json.loads(run_completed.stdout)["session"]["session_id"]
        watch_completed = self.run_aegis("watch", session_id, "--live", "--interval", "0.01")
        self.assertEqual(watch_completed.returncode, 0, watch_completed.stderr)
        self.assertIn("AEGIS AUTOPILOT", watch_completed.stdout)

    def test_ulw_live_renders_multiple_frames_while_running(self) -> None:
        completed = self.run_aegis("ulw", "修复登录 bug", "--live", "--interval", "0.01", "--step-delay", "0.02")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertGreaterEqual(completed.stdout.count("AEGIS AUTOPILOT"), 2)
        self.assertIn("running", completed.stdout)
        self.assertIn("completed", completed.stdout)

    def test_real_execute_reports_missing_runtime_clearly(self) -> None:
        completed = self.run_aegis("run", "修复登录 bug", "--execute", "--models", "missing-model", "--format", "json")
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertIn("error", payload)
        self.assertIn("registered", payload["error"])

    def test_explicit_pair_command_forces_pair_strategy(self) -> None:
        completed = self.run_aegis("pair", "实现 JWT 登录", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["route"]["strategy"], "pair")
        self.assertEqual([step["role"] for step in payload["plan"]["steps"]], ["builder", "reviewer"])

    def test_agents_list_uses_1_0_runtime_registry(self) -> None:
        completed = self.run_aegis("agents", "list", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        names = {item["name"] for item in payload}
        self.assertIn("codex", names)
        self.assertIn("claude", names)
        self.assertNotIn("ollama", names)

    def test_models_command_remains_a_compatibility_alias(self) -> None:
        completed = self.run_aegis("models", "list", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(any(item["name"] == "codex" for item in payload))

    def test_bridge_status_command_is_exposed(self) -> None:
        completed = self.run_aegis("bridge", "status", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("sessions", payload)

    def test_config_init_show_and_cost_report_are_available(self) -> None:
        init_completed = self.run_aegis("config", "init", "--format", "json")
        self.assertEqual(init_completed.returncode, 0, init_completed.stderr)
        init_payload = json.loads(init_completed.stdout)
        self.assertTrue((self.workspace_dir / ".aegis" / "aegis-1.json").exists())
        self.assertIn("config_path", init_payload)

        show_completed = self.run_aegis("config", "show", "--format", "json")
        self.assertEqual(show_completed.returncode, 0, show_completed.stderr)
        show_payload = json.loads(show_completed.stdout)
        self.assertEqual(show_payload["config"]["version"], "1.0")

        self.run_aegis("run", "修复登录 bug", "--simulate", "--format", "json")
        cost_completed = self.run_aegis("cost", "report", "--format", "json")
        self.assertEqual(cost_completed.returncode, 0, cost_completed.stderr)
        cost_payload = json.loads(cost_completed.stdout)
        self.assertGreaterEqual(cost_payload["session_count"], 1)
        self.assertIn("by_status", cost_payload)

    def test_doctor_reports_environment_checks(self) -> None:
        completed = self.run_aegis("doctor", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        names = {check["name"] for check in payload["checks"]}
        self.assertIn("python", names)
        self.assertIn("module:rich", names)
        self.assertIn("workspace", names)
        self.assertIn("write", names)

    def test_real_verification_failure_blocks_completion(self) -> None:
        (self.workspace_dir / ".aegis").mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / ".aegis" / "aegis-1.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "verification": {"commands": [["python3", "-c", "import sys; sys.exit(3)"]], "auto_detect": False},
                }
            ),
            encoding="utf-8",
        )
        paths = build_paths(self.workspace_dir)
        store = SessionStore(paths)
        route = IntentRouter().route("修复登录 bug", {"strategy": "pipeline"})
        plan = RunPlanner().build("修复登录 bug", route)
        session = store.create("修复登录 bug", route, plan, {"test": "verification"})

        class FakeRuntime:
            def complete(self, step: RunStep, *, session_id: str, prompt: str):
                del session_id, prompt

                class Result:
                    model = step.model
                    runtime = "fake"
                    output = "ok"
                    command = ["fake"]
                    log_path = ""
                    response_path = ""
                    duration_ms = 1

                return Result()

        with self.assertRaises(PolicyViolation):
            CollaborationEngine(store).execute(session.session_id, plan, simulate=False, runtime=FakeRuntime())
        latest = store.get(session.session_id)
        self.assertEqual(latest.status, "failed")
        events = [event.to_dict() for event in store.events(session.session_id)]
        self.assertTrue(any(event["event_type"] == "verification" and event["status"] == "failed" for event in events))
        self.assertTrue(any(event["event_type"] == "policy_violation" for event in events))

    def test_rich_tui_renderer_contains_core_sections(self) -> None:
        completed = self.run_aegis("pipeline", "修复登录 bug", "--simulate", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        session_id = json.loads(completed.stdout)["session"]["session_id"]
        store = SessionStore(build_paths(self.workspace_dir))
        console = Console(file=StringIO(), record=True, width=120)
        console.print(render_rich_cockpit(store, store.get(session_id)))
        rendered = console.export_text()
        self.assertIn("AEGIS AUTOPILOT", rendered)
        self.assertIn("任务进展", rendered)
        self.assertIn("八大底层能力", rendered)
        self.assertIn("双向共验证", rendered)
        self.assertIn("方圆会议", rendered)
        self.assertIn("十二铁律", rendered)

    def test_run_policy_blocks_false_completion_without_verify_and_done_gate(self) -> None:
        paths = build_paths(self.workspace_dir)
        store = SessionStore(paths)
        route = IntentRouter().route("修复登录 bug", {"strategy": "pipeline"})
        plan = RunPlanner().build("修复登录 bug", route)
        session = store.create("修复登录 bug", route, plan, {"test": "policy"})
        engine = CollaborationEngine(store)
        original_steps = list(plan.steps)
        plan.steps = [step for step in plan.steps if step.kind not in {"verify", "done_gate", "delivery"}]
        try:
            with self.assertRaises(PolicyViolation):
                engine.execute(session.session_id, plan, simulate=True)
        finally:
            plan.steps = original_steps
        record = store.get(session.session_id)
        self.assertEqual(record.status, "failed")
        events = [event.to_dict() for event in store.events(session.session_id)]
        violation = next(event for event in events if event["event_type"] == "policy_violation")
        self.assertIn("pipeline has no passed verification", violation["metadata"]["violations"])
        self.assertIn("recover", violation["metadata"]["recovery_hint"])


if __name__ == "__main__":
    unittest.main()
