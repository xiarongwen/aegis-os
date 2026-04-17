import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.automation_runner import cli as runner_cli
from tools.control_plane import cli as control_plane


def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


def init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "AEGIS Test"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "aegis@example.com"], check=True, capture_output=True, text=True)


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
        workflow_root = control_plane.workflow_root(workflow_id)
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
                            "write_scope": [".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", workflow_id)],
                            "acceptance_criteria": ["UI renders a bounded shell"],
                            "dry_reuse_targets": [".aegis/runs/{workflow}/l3-dev/frontend".replace("{workflow}", workflow_id)],
                            "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                        },
                        {
                            "id": "BE-1",
                            "title": "Build backend shell",
                            "owner": "backend-squad",
                            "stage": "L3_DEVELOP",
                            "depends_on": [],
                            "parallel_group": "ui-api",
                            "write_scope": [".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", workflow_id)],
                            "acceptance_criteria": ["API shell responds"],
                            "dry_reuse_targets": [".aegis/runs/{workflow}/l3-dev/backend".replace("{workflow}", workflow_id)],
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
                        "frontend-squad": [".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", workflow_id)],
                        "backend-squad": [".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", workflow_id)],
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
            elif state_name == "L4_REVIEW":
                target = workflow_root / "l4-validation"
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
        elif agent_id in {"frontend-squad", "backend-squad"}:
            slug = "frontend" if agent_id == "frontend-squad" else "backend"
            target = workflow_root / "l3-dev" / slug
            target.mkdir(parents=True, exist_ok=True)
            (target / "README.md").write_text(f"{agent_id} output\n", encoding="utf-8")
            state = control_plane.load_state(workflow_id)
            control_plane.write_json(
                target / "reuse-audit.json",
                {
                    "version": "1.0.0",
                    "workflow_id": workflow_id,
                    "agent_id": agent_id,
                    "generated_at": control_plane.utc_now(),
                    "requirements_lock_hash": state["requirements_lock_hash"],
                    "completed_tasks": ["FE-1"] if agent_id == "frontend-squad" else ["BE-1"],
                    "scanned_existing_assets": [f"src/{slug}", "src/lib"],
                    "reused_assets": [],
                    "new_assets": [f"src/{slug}/index.js"],
                    "duplication_risk_checks": [f"No existing {slug} implementation matched the locked requirements"],
                    "host_capabilities_used": [
                        {
                            "action": "resolve_host_capability",
                            "resolution": "used mapped host capability only",
                        }
                    ],
                    "verification_commands": ["npm test"],
                },
            )
        elif agent_id == "code-reviewer":
            target = workflow_root / "l3-dev"
            target.mkdir(parents=True, exist_ok=True)
            (target / "code-review-report.md").write_text("code review ok\n", encoding="utf-8")
            (target / "review-round-1.md").write_text("code review round ok\n", encoding="utf-8")
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
                    "reviewer": "code-reviewer",
                    "blockers": [],
                    "suggestions": [],
                    "approved_at": control_plane.utc_now(),
                },
            )
        elif agent_id == "security-auditor":
            target = workflow_root / "l3-dev"
            target.mkdir(parents=True, exist_ok=True)
            (target / "security-scan-report.md").write_text("security review ok\n", encoding="utf-8")
            (target / "review-round-1.md").write_text("security review round ok\n", encoding="utf-8")
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
                    "score": 9.4,
                    "reviewer": "security-auditor",
                    "blockers": [],
                    "suggestions": [],
                    "approved_at": control_plane.utc_now(),
                },
            )
        elif agent_id == "qa-validator":
            target = workflow_root / "l4-validation"
            target.mkdir(parents=True, exist_ok=True)
            (target / "test-report.md").write_text("qa ok\n", encoding="utf-8")
            control_plane.write_json(
                target / "qa-signoff.json",
                {
                    "status": "approved",
                    "signed_off_by": "qa-validator",
                    "approved_at": control_plane.utc_now(),
                },
            )
            control_plane.write_json(
                target / "requirements-traceability.json",
                {
                    "workflow_id": workflow_id,
                    "requirements_lock_hash": control_plane.load_state(workflow_id)["requirements_lock_hash"],
                    "covered_stories": [
                        {
                            "id": "USR-1",
                            "evidence": ["test-report.md", "../l3-dev/frontend/README.md", "../l3-dev/backend/README.md"],
                        }
                    ],
                    "uncovered_items": [],
                    "approved_at": control_plane.utc_now(),
                },
            )
        else:
            raise AssertionError(f"unexpected fake adapter agent: {agent_id}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(prompt, encoding="utf-8")
        return runner_cli.RuntimeResult(command=["fake"], output_path=log_path)


class AutomationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-workspace-"))
        self.team_home = Path(tempfile.mkdtemp(prefix="aegis-team-home-"))
        self.skills_dir = Path(tempfile.mkdtemp(prefix="aegis-team-skills-"))
        self.commands_dir = Path(tempfile.mkdtemp(prefix="aegis-team-commands-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(
            os.environ,
            {
                "AEGIS_WORKSPACE_ROOT": str(self.workspace_dir),
                "AEGIS_TEAM_HOME": str(self.team_home),
            },
        )
        self.skills_patch = patch.object(control_plane, "SKILLS_DIR", self.skills_dir)
        self.commands_patch = patch.object(control_plane, "CLAUDE_COMMANDS_DIR", self.commands_dir)
        self.env_patch.start()
        self.skills_patch.start()
        self.commands_patch.start()
        control_plane.ensure_workspace_layout()

    def tearDown(self) -> None:
        self.commands_patch.stop()
        self.skills_patch.stop()
        self.env_patch.stop()
        for workflow_id in [
            "planning-mvp-test",
            "build-mvp-test",
            "build-e2e-test",
            "human-pause-test",
            "snapshot-freeze-test",
        ]:
            shutil.rmtree(control_plane.workflow_root(workflow_id), ignore_errors=True)
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        shutil.rmtree(self.team_home, ignore_errors=True)
        shutil.rmtree(self.skills_dir, ignore_errors=True)
        shutil.rmtree(self.commands_dir, ignore_errors=True)

    def test_route_request_for_prd_goal(self) -> None:
        route = runner_cli.route_request("帮我调研一个项目并输出 PRD")
        self.assertEqual(route.workflow_type, "planning")
        self.assertEqual(route.target_state, "L2_REVIEW")

    def test_route_request_for_build_goal(self) -> None:
        route = runner_cli.route_request("帮我开发一个聊天页面")
        self.assertEqual(route.workflow_type, "build")
        self.assertEqual(route.target_state, "L4_REVIEW")

    def test_route_request_for_team_creation_goal(self) -> None:
        route = runner_cli.route_request("/aegis 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video")
        self.assertEqual(route.mode, "team_pack")
        self.assertEqual(route.workflow_type, "team_pack_compose")
        self.assertEqual(route.team_action, "compose")
        self.assertEqual(route.team_id, "AEGIS-video")
        self.assertEqual(route.team_scope, "global")

    def test_route_request_for_team_invocation_goal(self) -> None:
        route = runner_cli.route_request("AEGIS-video 帮我做一个短视频方案，重点是 hook 和字幕节奏。")
        self.assertEqual(route.mode, "team_pack")
        self.assertEqual(route.workflow_type, "team_pack_run")
        self.assertEqual(route.team_action, "invoke")
        self.assertEqual(route.team_id, "AEGIS-video")
        self.assertTrue(route.team_request.startswith("帮我做一个短视频方案"))

    def test_runner_completes_planning_target(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            result = runner.run_request("帮我调研一个项目并输出 PRD", workflow_id="planning-mvp-test")
        self.assertEqual(result["status"], "completed_target")
        self.assertEqual(result["current_state"], "L2_REVIEW")
        self.assertEqual(result["next_state_hint"], "L3_DEVELOP")
        intent_lock = control_plane.load_json(runner_cli.intent_lock_path("planning-mvp-test"))
        self.assertEqual(intent_lock["workflow_type"], "planning")

    def test_runner_completes_build_target_end_to_end(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=20)
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            result = runner.run_request("帮我开发一个聊天页面", workflow_id="build-e2e-test")
        self.assertEqual(result["status"], "completed_target")
        self.assertEqual(result["current_state"], "L4_REVIEW")
        self.assertEqual(result["next_state_hint"], "L5_DEPLOY")
        self.assertEqual(len(result["steps"]), 10)
        self.assertTrue((control_plane.workflow_root("build-e2e-test") / "l3-dev" / "frontend" / "reuse-audit.json").exists())
        self.assertTrue((control_plane.workflow_root("build-e2e-test") / "l3-dev" / "backend" / "reuse-audit.json").exists())
        self.assertTrue((control_plane.workflow_root("build-e2e-test") / "l4-validation" / "requirements-traceability.json").exists())

    def test_bootstrap_summary_creates_host_native_workflow(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("帮我调研一个项目并输出 PRD", workflow_id="build-mvp-test")
        self.assertEqual(summary["status"], "bootstrapped")
        self.assertEqual(summary["current_state"], "L1_RESEARCH")
        intent_lock = control_plane.load_json(runner_cli.intent_lock_path("build-mvp-test"))
        self.assertEqual(intent_lock["status"], "locked")
        self.assertEqual(intent_lock["workflow_type"], "planning")
        self.assertTrue(control_plane.project_lock_path("build-mvp-test").exists())
        self.assertTrue(control_plane.registry_lock_path("build-mvp-test").exists())
        self.assertTrue(control_plane.orchestrator_lock_path("build-mvp-test").exists())

    def test_runtime_snapshot_remains_frozen_after_project_manifest_changes(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("帮我调研一个项目并输出 PRD", workflow_id="snapshot-freeze-test")
        self.assertEqual(summary["status"], "bootstrapped")

        original_project_lock = control_plane.load_json(control_plane.project_lock_path("snapshot-freeze-test"))
        updated_manifest = control_plane.load_json(control_plane.project_manifest_path())
        updated_manifest["project_id"] = "mutated-project-id"
        control_plane.write_json(control_plane.project_manifest_path(), updated_manifest)

        locked_project, _, _, _ = control_plane.get_runtime_context("snapshot-freeze-test")
        self.assertEqual(locked_project["project_id"], original_project_lock["project_id"])
        self.assertNotEqual(locked_project["project_id"], updated_manifest["project_id"])
        self.assertEqual(control_plane.run_doctor("snapshot-freeze-test")[0], "runtime snapshot valid: .aegis/runs/snapshot-freeze-test/project-lock.json")

    def test_bootstrap_rejects_disabled_workflow_type(self) -> None:
        manifest = control_plane.load_json(control_plane.project_manifest_path())
        manifest["enabled_workflows"] = ["research"]
        control_plane.write_json(control_plane.project_manifest_path(), manifest)
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        with self.assertRaisesRegex(runner_cli.AutomationRunnerError, "workflow type `build` is disabled"):
            runner.bootstrap_summary("帮我开发一个聊天页面", workflow_id="disabled-build-test")

    def test_runner_pauses_before_human_required_state(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before={"L5_DEPLOY"}, max_steps=10)
        workflow_id, route = runner.bootstrap("帮我开发一个聊天页面", workflow_id="human-pause-test")
        state = control_plane.load_state(workflow_id)
        state["current_state"] = "L5_DEPLOY"
        control_plane.write_json(control_plane.state_path(workflow_id), state)
        result = runner.resume(workflow_id, route=route)
        self.assertEqual(result["status"], "paused_for_human")
        self.assertEqual(result["current_state"], "L5_DEPLOY")

    def test_bootstrap_summary_creates_team_pack_for_team_request(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("AEGIS 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video")
        self.assertEqual(summary["status"], "team_pack_ready")
        self.assertEqual(summary["team_id"], "AEGIS-video")
        self.assertTrue(summary["installed"])
        manifest_path = self.team_home / "teams" / "global" / "AEGIS-video" / "team.json"
        self.assertTrue(manifest_path.exists())
        self.assertTrue((self.skills_dir / "aegis-video").is_symlink())
        self.assertTrue((self.commands_dir / "aegis-video.md").is_symlink())

    def test_run_request_prepares_team_run_for_installed_team(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        runner.bootstrap_summary("AEGIS 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video")
        summary = runner.run_request("AEGIS-video 帮我做一个 hook 很强的短视频脚本")
        self.assertEqual(summary["status"], "team_run_prepared")
        self.assertEqual(summary["team_id"], "AEGIS-video")
        self.assertTrue(summary["run_id"].startswith("aegis-video-"))
        self.assertTrue((self.team_home / "teams" / "global" / "AEGIS-video" / "runs" / f"{summary['run_id']}.brief.json").exists())
        self.assertIn("team_memory_markdown:", "\n".join(summary["messages"]))


if __name__ == "__main__":
    unittest.main()
