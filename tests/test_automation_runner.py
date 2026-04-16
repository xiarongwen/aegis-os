import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.automation_runner import cli as runner_cli
from tools.control_plane import cli as control_plane


def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


class FakeAdapter(runner_cli.RuntimeAdapter):
    name = "fake"

    def run(
        self,
        *,
        agent_id: str,
        workflow_id: str,
        state_name: str,
        prompt: str,
        log_path: Path,
        use_search: bool,
    ) -> runner_cli.RuntimeResult:
        workflow_root = runner_cli.ROOT / "workflows" / workflow_id
        if agent_id == "market-research":
            target = workflow_root / "l1-intelligence"
            target.mkdir(parents=True, exist_ok=True)
            for name in ["market_report.md", "competitive_analysis.md", "tech_feasibility.md"]:
                (target / name).write_text(f"{name}\n", encoding="utf-8")
        elif agent_id == "prd-architect":
            target = workflow_root / "l2-planning"
            target.mkdir(parents=True, exist_ok=True)
            (target / "PRD.md").write_text("# PRD\n", encoding="utf-8")
            (target / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
            control_plane.write_json(
                target / "task_breakdown.json",
                {
                    "version": "1.0.0",
                    "workflow_id": workflow_id,
                    "created_at": control_plane.utc_now(),
                    "planning_mode": "l3_parallel_execution",
                    "development_principles": [
                        "dry_first",
                        "parallel_by_default",
                        "contract_before_code",
                        "owned_write_scope",
                        "host_capability_enhancement",
                    ],
                    "parallel_execution": {
                        "default_mode": "parallel_by_default",
                        "max_parallel_agents": 2,
                    },
                    "tasks": [
                        {
                            "id": "FE-1",
                            "title": "Build frontend shell",
                            "owner": "frontend-squad",
                            "stage": "L3_DEVELOP",
                            "depends_on": [],
                            "parallel_group": "ui-api",
                            "write_scope": ["workflows/{workflow}/l3-dev/frontend/**".replace("{workflow}", workflow_id)],
                            "acceptance_criteria": ["UI renders a bounded shell"],
                            "dry_reuse_targets": ["workflows/{workflow}/l3-dev/frontend".replace("{workflow}", workflow_id)],
                            "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                        },
                        {
                            "id": "BE-1",
                            "title": "Build backend shell",
                            "owner": "backend-squad",
                            "stage": "L3_DEVELOP",
                            "depends_on": [],
                            "parallel_group": "ui-api",
                            "write_scope": ["workflows/{workflow}/l3-dev/backend/**".replace("{workflow}", workflow_id)],
                            "acceptance_criteria": ["API shell responds"],
                            "dry_reuse_targets": ["workflows/{workflow}/l3-dev/backend".replace("{workflow}", workflow_id)],
                            "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                        },
                    ],
                },
            )
            control_plane.write_json(
                target / "implementation-contracts.json",
                {
                    "version": "1.0.0",
                    "workflow_id": workflow_id,
                    "generated_at": control_plane.utc_now(),
                    "contract_version": "1.0.0",
                    "shared_interfaces": [],
                    "owned_write_scopes": {
                        "frontend-squad": ["workflows/{workflow}/l3-dev/frontend/**".replace("{workflow}", workflow_id)],
                        "backend-squad": ["workflows/{workflow}/l3-dev/backend/**".replace("{workflow}", workflow_id)],
                    },
                    "integration_rules": {
                        "required_before_parallel": ["contract_before_code"],
                    },
                    "change_control": {"owner": "user", "mode": "explicit_approval"},
                },
            )
            control_plane.write_json(
                target / "requirements-lock.json",
                {
                    "version": "1.0.0",
                    "workflow_id": workflow_id,
                    "source_stage": "L2_PLANNING",
                    "locked_at": control_plane.utc_now(),
                    "product_goal": "Produce a locked PRD for the request",
                    "scope": {"in": ["PRD", "architecture", "task breakdown"], "out": ["implementation"]},
                    "user_stories": [],
                    "non_functional_requirements": [],
                    "assumptions": [],
                    "change_control": {"owner": "user", "mode": "explicit_approval"},
                    "lock_hash": "",
                },
            )
        elif agent_id == "research-qa-agent":
            if state_name == "L1_REVIEW":
                target = workflow_root / "l1-intelligence"
            elif state_name == "L2_REVIEW":
                target = workflow_root / "l2-planning"
            else:
                raise AssertionError(f"unexpected state for fake reviewer: {state_name}")
            (target / "gate-review-report.md").write_text("gate ok\n", encoding="utf-8")
            (target / "review-round-1.md").write_text("round ok\n", encoding="utf-8")
            control_plane.write_json(
                target / "review-loop-status.json",
                {
                    "workflow_id": workflow_id,
                    "gate": state_name,
                    "round": 1,
                    "status": "lgtm",
                    "verdict": "LGTM",
                    "open_issues": [],
                    "closed_issues": [],
                    "lgtm": True,
                    "max_rounds": 3,
                    "updated_at": control_plane.utc_now(),
                },
            )
            control_plane.write_json(
                target / "review-passed.json",
                {
                    "score": 8.8,
                    "reviewer": "research-qa-agent",
                    "blockers": [],
                    "suggestions": [],
                    "approved_at": control_plane.utc_now(),
                },
            )
        else:
            raise AssertionError(f"unexpected fake adapter agent: {agent_id}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(prompt, encoding="utf-8")
        return runner_cli.RuntimeResult(command=["fake"], output_path=log_path)


class AutomationRunnerTests(unittest.TestCase):
    def tearDown(self) -> None:
        for workflow_id in [
            "planning-mvp-test",
            "build-mvp-test",
            "human-pause-test",
        ]:
            shutil.rmtree(runner_cli.ROOT / "workflows" / workflow_id, ignore_errors=True)

    def test_route_request_for_prd_goal(self) -> None:
        route = runner_cli.route_request("帮我调研一个项目并输出 PRD")
        self.assertEqual(route.workflow_type, "planning")
        self.assertEqual(route.target_state, "L2_REVIEW")

    def test_route_request_for_build_goal(self) -> None:
        route = runner_cli.route_request("帮我开发一个聊天页面")
        self.assertEqual(route.workflow_type, "build")
        self.assertEqual(route.target_state, "L4_REVIEW")

    def test_runner_completes_planning_target(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            result = runner.run_request("帮我调研一个项目并输出 PRD", workflow_id="planning-mvp-test")
        self.assertEqual(result["status"], "completed_target")
        self.assertEqual(result["current_state"], "L2_REVIEW")
        self.assertEqual(result["next_state_hint"], "L3_DEVELOP")
        intent_lock = control_plane.load_json(runner_cli.intent_lock_path("planning-mvp-test"))
        self.assertEqual(intent_lock["workflow_type"], "planning")

    def test_bootstrap_summary_creates_host_native_workflow(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("帮我调研一个项目并输出 PRD", workflow_id="build-mvp-test")
        self.assertEqual(summary["status"], "bootstrapped")
        self.assertEqual(summary["current_state"], "L1_RESEARCH")
        intent_lock = control_plane.load_json(runner_cli.intent_lock_path("build-mvp-test"))
        self.assertEqual(intent_lock["status"], "locked")
        self.assertEqual(intent_lock["workflow_type"], "planning")

    def test_runner_pauses_before_human_required_state(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before={"L5_DEPLOY"}, max_steps=10)
        workflow_id, route = runner.bootstrap("帮我开发一个聊天页面", workflow_id="human-pause-test")
        state = control_plane.load_state(workflow_id)
        state["current_state"] = "L5_DEPLOY"
        control_plane.write_json(control_plane.state_path(workflow_id), state)
        result = runner.resume(workflow_id, route=route)
        self.assertEqual(result["status"], "paused_for_human")
        self.assertEqual(result["current_state"], "L5_DEPLOY")


if __name__ == "__main__":
    unittest.main()
