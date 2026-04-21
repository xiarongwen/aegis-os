import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.aegis_v2.config import build_paths
from tools.aegis_v2.registry import ModelRegistry
from tools.aegis_v2.router import TaskRouter
from tools.aegis_v2.session import SessionStore


def init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "AEGIS Test"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "aegis@example.com"], check=True, capture_output=True, text=True)


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

    def test_router_dry_run_prefers_quality_architecture_model(self) -> None:
        completed = self.run_aegis("router", "dry-run", "设计并重构用户权限系统架构", "--mode", "quality", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["task_type"], "architecture")
        self.assertEqual(payload["strategy"], "single")
        self.assertEqual(payload["models"], ["claude-opus-4-7"])

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

    def test_collaboration_pair_forces_pair_strategy(self) -> None:
        completed = self.run_aegis("collaboration", "pair", "重构认证模块并保持行为不变", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["routing"]["strategy"], "pair")
        self.assertEqual(payload["plan"]["steps"][0]["kind"], "coder")
        self.assertEqual(payload["plan"]["steps"][1]["kind"], "reviewer")

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

    def test_execute_simulated_pair_records_review_feedback(self) -> None:
        completed = self.run_aegis(
            "collaboration",
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
