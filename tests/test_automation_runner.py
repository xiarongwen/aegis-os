import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.automation_runner import cli as runner_cli
from tools.control_plane import cli as control_plane


class StreamingPopen:
    def __init__(self, args: list[str], stdout_text: str = "", stderr_text: str = "", returncode: int = 0) -> None:
        self.args = args
        self.pid = 12345
        self.returncode = returncode
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: int | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class StepClock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> float:
        if self.index >= len(self.values):
            return self.values[-1]
        value = self.values[self.index]
        self.index += 1
        return value


def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    if args[:2] == ("check-ignore", "-q"):
        return subprocess.CompletedProcess(["git", *args], 1, "", "")
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


def init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "AEGIS Test"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "aegis@example.com"], check=True, capture_output=True, text=True)


def write_review_gate_pass(workflow_id: str, gate_dir: Path, gate: str, reviewer: str) -> None:
    (gate_dir / "gate-review-report.md").write_text("gate ok\n", encoding="utf-8")
    (gate_dir / "review-round-1.md").write_text("round ok\n", encoding="utf-8")
    control_plane.write_json(
        gate_dir / "review-loop-status.json",
        {
            "workflow_id": workflow_id,
            "gate": gate,
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
        gate_dir / "review-passed.json",
        {
            "score": 8.8,
            "reviewer": reviewer,
            "blockers": [],
            "suggestions": [],
            "approved_at": control_plane.utc_now(),
        },
    )


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
        event_callback: runner_cli.EventCallback | None = None,
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
        for workflow_id in [
            "planning-mvp-test",
            "build-mvp-test",
            "build-e2e-test",
            "human-pause-test",
            "snapshot-freeze-test",
            "prompt-runtime-test",
        ]:
            shutil.rmtree(control_plane.workflow_root(workflow_id, self.workspace_dir), ignore_errors=True)
        self.commands_patch.stop()
        self.skills_patch.stop()
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        shutil.rmtree(self.team_home, ignore_errors=True)
        shutil.rmtree(self.skills_dir, ignore_errors=True)
        shutil.rmtree(self.commands_dir, ignore_errors=True)

    def test_route_request_for_prd_goal(self) -> None:
        route = runner_cli.route_request("帮我调研一个项目并输出 PRD")
        self.assertEqual(route.workflow_type, "planning")
        self.assertEqual(route.entry_state, "L1_RESEARCH")
        self.assertEqual(route.target_state, "L2_REVIEW")
        self.assertEqual(route.execution_plan, ["research", "planning", "review"])

    def test_route_request_for_build_goal(self) -> None:
        route = runner_cli.route_request("帮我开发一个聊天页面")
        self.assertEqual(route.workflow_type, "build")
        self.assertEqual(route.entry_state, "L1_RESEARCH")
        self.assertEqual(route.target_state, "L4_REVIEW")
        self.assertEqual(route.execution_plan, ["research", "planning", "build", "validate", "review"])

    def test_route_request_for_web_demo_goal(self) -> None:
        route = runner_cli.route_request("帮我写一个太阳系运行的网页demo")
        self.assertEqual(route.workflow_type, "build")
        self.assertEqual(route.entry_state, "L3_DEVELOP")
        self.assertEqual(route.target_state, "L4_REVIEW")
        self.assertEqual(route.execution_plan, ["build", "validate", "review"])

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

    def test_prompt_uses_workspace_local_runtime_assets(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("帮我调研一个项目并输出 PRD", workflow_id="prompt-runtime-test")
        self.assertEqual(summary["status"], "bootstrapped")
        registry = control_plane.load_json(control_plane.registry_lock_path("prompt-runtime-test"))
        agent = control_plane.registry_by_id(registry)["market-research"]
        route = runner.load_route("prompt-runtime-test")
        prompt = runner_cli.prompt_for_agent(
            workflow_id="prompt-runtime-test",
            agent=agent,
            state_name="L1_RESEARCH",
            route=route,
        )
        expected_skill_path = control_plane.runtime_agent_file_path(
            "market-research",
            "SKILL.md",
            workflow="prompt-runtime-test",
        ).resolve()
        expected_workspace_root = self.workspace_dir.resolve()
        self.assertIn(str(expected_workspace_root), prompt)
        self.assertIn(str(expected_skill_path), prompt)
        self.assertTrue(str(expected_skill_path).startswith(str((expected_workspace_root / ".aegis" / "agents").resolve())))

    def test_workflow_index_persists_under_team_home_control_plane(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("帮我调研一个项目并输出 PRD", workflow_id="build-mvp-test")
        self.assertEqual(summary["status"], "bootstrapped")
        index_path = control_plane.workflow_index_path().resolve()
        self.assertEqual(index_path, (self.team_home / "control-plane" / "workflow-index.json").resolve())
        payload = control_plane.load_json(index_path)
        self.assertEqual(payload["workflows"]["build-mvp-test"]["workspace_root"], str(self.workspace_dir.resolve()))

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

    def test_dispatch_workers_runs_parallel_l3_workers(self) -> None:
        workflow_id = "prompt-runtime-test"
        runner = runner_cli.AutomationRunner(adapter=FakeAdapter(), stop_before=set(), max_steps=10)
        runner.bootstrap_summary("帮我开发一个聊天页面", workflow_id=workflow_id)
        workflow_root = control_plane.workflow_root(workflow_id)

        l1_dir = workflow_root / "l1-intelligence"
        l1_dir.mkdir(parents=True, exist_ok=True)
        for name in ["market_report.md", "competitive_analysis.md", "tech_feasibility.md"]:
            (l1_dir / name).write_text(f"{name}\n", encoding="utf-8")
        l2_dir = workflow_root / "l2-planning"
        l2_dir.mkdir(parents=True, exist_ok=True)
        (l2_dir / "PRD.md").write_text("# PRD\n", encoding="utf-8")
        (l2_dir / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
        control_plane.write_json(
            l2_dir / "task_breakdown.json",
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
                        "write_scope": [f".aegis/runs/{workflow_id}/l3-dev/frontend/**"],
                        "acceptance_criteria": ["UI renders a bounded shell"],
                        "dry_reuse_targets": [f".aegis/runs/{workflow_id}/l3-dev/frontend"],
                        "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                    },
                    {
                        "id": "BE-1",
                        "title": "Build backend shell",
                        "owner": "backend-squad",
                        "stage": "L3_DEVELOP",
                        "depends_on": [],
                        "parallel_group": "ui-api",
                        "write_scope": [f".aegis/runs/{workflow_id}/l3-dev/backend/**"],
                        "acceptance_criteria": ["API shell responds"],
                        "dry_reuse_targets": [f".aegis/runs/{workflow_id}/l3-dev/backend"],
                        "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                    },
                ],
            },
        )
        control_plane.write_json(
            l2_dir / "implementation-contracts.json",
            {
                "version": "1.0.0",
                "workflow_id": workflow_id,
                "generated_at": control_plane.utc_now(),
                "contract_version": "1.0.0",
                "shared_interfaces": [],
                "owned_write_scopes": {
                    "frontend-squad": [f".aegis/runs/{workflow_id}/l3-dev/frontend/**"],
                    "backend-squad": [f".aegis/runs/{workflow_id}/l3-dev/backend/**"],
                },
                "integration_rules": {
                    "required_before_parallel": ["contract_before_code"],
                },
                "change_control": {"owner": "user", "mode": "explicit_approval"},
            },
        )
        control_plane.write_json(
            l2_dir / "requirements-lock.json",
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

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            control_plane.post_agent_run("market-research", workflow_id)
            control_plane.write_state_transition(workflow_id, "L1_REVIEW")
            write_review_gate_pass(workflow_id, l1_dir, "L1_REVIEW", "research-qa-agent")
            control_plane.post_agent_run("research-qa-agent", workflow_id)
            control_plane.write_state_transition(workflow_id, "L2_PLANNING")
            control_plane.post_agent_run("prd-architect", workflow_id)
            control_plane.write_state_transition(workflow_id, "L2_REVIEW")
            write_review_gate_pass(workflow_id, l2_dir, "L2_REVIEW", "research-qa-agent")
            control_plane.post_agent_run("research-qa-agent", workflow_id)
            control_plane.write_state_transition(workflow_id, "L3_DEVELOP")

        class DummyPopen:
            def __init__(self, args: list[str]) -> None:
                self.args = args
                self.returncode = 0
                self.pid = 12345
                self.stdout = io.StringIO("")
                self.stderr = io.StringIO("")

            def poll(self) -> int | None:
                return self.returncode

            def wait(self, timeout: int | None = None) -> int:
                return self.returncode

            def kill(self) -> None:
                self.returncode = -9

        def fake_popen(
            cmd: list[str],
            cwd: str | None = None,
            env: dict[str, str] | None = None,
            stdout: object | None = None,
            stderr: object | None = None,
            text: bool | None = None,
            bufsize: int | None = None,
        ) -> DummyPopen:
            prompt = cmd[-1]
            log_path = Path(cmd[cmd.index("-o") + 1])
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(prompt, encoding="utf-8")
            state = control_plane.load_state(workflow_id)
            if "`frontend-squad`" in prompt:
                target = workflow_root / "l3-dev" / "frontend"
                target.mkdir(parents=True, exist_ok=True)
                (target / "README.md").write_text("frontend output\n", encoding="utf-8")
                control_plane.write_json(
                    target / "reuse-audit.json",
                    {
                        "version": "1.0.0",
                        "workflow_id": workflow_id,
                        "agent_id": "frontend-squad",
                        "generated_at": control_plane.utc_now(),
                        "requirements_lock_hash": state["requirements_lock_hash"],
                        "completed_tasks": ["FE-1"],
                        "scanned_existing_assets": ["src/frontend", "src/lib"],
                        "reused_assets": [],
                        "new_assets": ["src/frontend/index.js"],
                        "duplication_risk_checks": ["No existing frontend implementation matched the locked requirements"],
                        "host_capabilities_used": [
                            {"action": "resolve_host_capability", "resolution": "used mapped host capability only"}
                        ],
                        "verification_commands": ["npm test"],
                    },
                )
            elif "`backend-squad`" in prompt:
                target = workflow_root / "l3-dev" / "backend"
                target.mkdir(parents=True, exist_ok=True)
                (target / "README.md").write_text("backend output\n", encoding="utf-8")
                control_plane.write_json(
                    target / "reuse-audit.json",
                    {
                        "version": "1.0.0",
                        "workflow_id": workflow_id,
                        "agent_id": "backend-squad",
                        "generated_at": control_plane.utc_now(),
                        "requirements_lock_hash": state["requirements_lock_hash"],
                        "completed_tasks": ["BE-1"],
                        "scanned_existing_assets": ["src/backend", "src/lib"],
                        "reused_assets": [],
                        "new_assets": ["src/backend/index.js"],
                        "duplication_risk_checks": ["No existing backend implementation matched the locked requirements"],
                        "host_capabilities_used": [
                            {"action": "resolve_host_capability", "resolution": "used mapped host capability only"}
                        ],
                        "verification_commands": ["pytest"],
                    },
                )
            return DummyPopen(cmd)

        codex_runner = runner_cli.AutomationRunner(adapter=runner_cli.CodexRuntimeAdapter(), stop_before=set(), max_steps=10)
        with patch("tools.automation_runner.cli.subprocess.Popen", side_effect=fake_popen), patch(
            "tools.control_plane.cli.git", side_effect=fake_git
        ):
            result = codex_runner.dispatch_workers(
                workflow_id,
                runtime_choice=runner_cli.RuntimeChoice("codex", "test-selected codex"),
            )

        self.assertEqual(result["status"], "workers_completed")
        self.assertEqual(result["state"], "L3_DEVELOP")
        self.assertEqual(result["runtime"], "codex")
        self.assertEqual(result["runtime_rationale"], "test-selected codex")
        self.assertEqual(len(result["steps"]), 2)
        self.assertTrue(
            any(
                "committed workflow changes" in line
                or "no workflow changes" in line
                or "workflow changes are gitignored; skipping commit" in line
                for line in result["messages"]
            )
        )
        self.assertTrue((workflow_root / "l3-dev" / "frontend" / "reuse-audit.json").exists())
        self.assertTrue((workflow_root / "l3-dev" / "backend" / "reuse-audit.json").exists())

    def test_codex_runtime_adapter_uses_codex_exec(self) -> None:
        adapter = runner_cli.CodexRuntimeAdapter()
        log_path = self.workspace_dir / "codex.log"
        expected_workspace = str(self.workspace_dir.resolve())
        with patch("tools.automation_runner.cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = StreamingPopen(["codex"], stdout_text="progress\n")
            result = adapter.run(
                agent_id="market-research",
                workflow_id="prompt-runtime-test",
                state_name="L1_RESEARCH",
                prompt="hello",
                log_path=log_path,
                use_search=True,
            )

        self.assertEqual(result.output_path, log_path)
        _, kwargs = mock_popen.call_args
        self.assertEqual(kwargs["env"]["AEGIS_WORKSPACE_ROOT"], expected_workspace)
        self.assertEqual(kwargs["env"]["AEGIS_CORE_ROOT"], str(control_plane.ROOT))
        self.assertEqual(
            mock_popen.call_args.args[0][:7],
            ["codex", "--search", "exec", "--full-auto", "-C", expected_workspace, "-o"],
        )

    def test_claude_runtime_adapter_uses_claude_print_mode_with_workspace_access(self) -> None:
        adapter = runner_cli.ClaudeRuntimeAdapter()
        log_path = self.workspace_dir / "claude.log"
        expected_workspace = str(self.workspace_dir.resolve())
        with patch("tools.automation_runner.cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = StreamingPopen(["claude"], stdout_text="agent output\n")
            result = adapter.run(
                agent_id="market-research",
                workflow_id="prompt-runtime-test",
                state_name="L1_RESEARCH",
                prompt="hello",
                log_path=log_path,
                use_search=False,
            )

        self.assertEqual(result.output_path, log_path)
        self.assertIn("agent output", log_path.read_text(encoding="utf-8"))
        _, kwargs = mock_popen.call_args
        self.assertEqual(kwargs["cwd"], expected_workspace)
        self.assertEqual(kwargs["env"]["AEGIS_WORKSPACE_ROOT"], expected_workspace)
        self.assertEqual(kwargs["env"]["AEGIS_CORE_ROOT"], str(control_plane.ROOT))
        self.assertEqual(
            mock_popen.call_args.args[0][:9],
            [
                "claude",
                "-p",
                "--bare",
                "--permission-mode",
                "bypassPermissions",
                "--output-format",
                "text",
                "--add-dir",
                expected_workspace,
            ],
        )

    def test_claude_runtime_idle_timeout_writes_log_stub(self) -> None:
        adapter = runner_cli.ClaudeRuntimeAdapter()
        log_path = self.workspace_dir / "claude-timeout.log"
        class HungAfterOutputPopen(StreamingPopen):
            def __init__(self) -> None:
                super().__init__(["claude"], stdout_text="started\n")

            def poll(self) -> int | None:
                return None

        with patch("tools.automation_runner.cli.DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS", 0), patch(
            "tools.automation_runner.cli.DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS",
            20,
        ), patch(
            "tools.automation_runner.cli.subprocess.Popen",
            return_value=HungAfterOutputPopen(),
        ):
            with self.assertRaisesRegex(runner_cli.AutomationRunnerError, "became idle"):
                adapter.run(
                    agent_id="market-research",
                    workflow_id="prompt-runtime-test",
                    state_name="L1_RESEARCH",
                    prompt="hello",
                    log_path=log_path,
                    use_search=False,
                )
        self.assertTrue(log_path.exists())
        self.assertIn("became idle", log_path.read_text(encoding="utf-8"))

    def test_claude_runtime_adapter_emits_stream_events(self) -> None:
        adapter = runner_cli.ClaudeRuntimeAdapter()
        log_path = self.workspace_dir / "claude-events.log"
        events: list[dict[str, object]] = []
        with patch(
            "tools.automation_runner.cli.subprocess.Popen",
            return_value=StreamingPopen(["claude"], stdout_text="line one\nline two\n"),
        ):
            adapter.run(
                agent_id="market-research",
                workflow_id="prompt-runtime-test",
                state_name="L1_RESEARCH",
                prompt="hello",
                log_path=log_path,
                use_search=False,
                event_callback=events.append,
            )
        self.assertTrue(any(event.get("kind") == "agent_started" for event in events))
        self.assertTrue(any(event.get("kind") == "agent_output" and event.get("text") == "line one" for event in events))
        self.assertTrue(any(event.get("kind") == "agent_completed" for event in events))

    def test_claude_runtime_continues_while_streaming_output(self) -> None:
        adapter = runner_cli.ClaudeRuntimeAdapter()
        log_path = self.workspace_dir / "claude-streaming.log"
        events: list[dict[str, object]] = []

        class LongStreamingPopen(StreamingPopen):
            def __init__(self) -> None:
                super().__init__(["claude"], stdout_text="tick1\ntick2\ntick3\n")

        monotonic = StepClock([0.0, 0.0, 0.5, 1.2, 1.8, 2.4, 2.9])
        with patch("tools.automation_runner.cli.DEFAULT_RUNTIME_IDLE_TIMEOUT_SECONDS", 1), patch(
            "tools.automation_runner.cli.DEFAULT_RUNTIME_SILENT_TIMEOUT_SECONDS",
            5,
        ), patch("tools.automation_runner.cli.time.monotonic", side_effect=monotonic), patch(
            "tools.automation_runner.cli.subprocess.Popen",
            return_value=LongStreamingPopen(),
        ):
            result = adapter.run(
                agent_id="market-research",
                workflow_id="prompt-runtime-test",
                state_name="L1_RESEARCH",
                prompt="hello",
                log_path=log_path,
                use_search=False,
                event_callback=events.append,
            )

        self.assertEqual(result.output_path, log_path)
        self.assertTrue(any(event.get("kind") == "agent_completed" for event in events))
        self.assertFalse(any(event.get("kind") == "agent_timeout" for event in events))

    def test_codex_runtime_uses_bridge_when_enabled(self) -> None:
        adapter = runner_cli.CodexRuntimeAdapter()
        log_path = self.workspace_dir / "codex-bridge.log"
        with patch.dict(os.environ, {"AEGIS_RUNTIME_BRIDGE": "tmux"}, clear=False):
            with patch("tools.automation_runner.cli.run_invocation_via_bridge") as bridge_run:
                bridge_run.return_value = runner_cli.RuntimeResult(command=["codex", "exec"], output_path=log_path)
                result = adapter.run(
                    agent_id="frontend-squad",
                    workflow_id="prompt-runtime-test",
                    state_name="L3_DEVELOP",
                    prompt="hello",
                    log_path=log_path,
                    use_search=False,
                )
        bridge_run.assert_called_once()
        self.assertEqual(result.output_path, log_path)

    def test_codex_runtime_falls_back_when_bridge_unavailable(self) -> None:
        adapter = runner_cli.CodexRuntimeAdapter()
        log_path = self.workspace_dir / "codex-fallback.log"
        events: list[dict[str, object]] = []
        with patch.dict(os.environ, {"AEGIS_RUNTIME_BRIDGE": "tmux"}, clear=False):
            with patch(
                "tools.automation_runner.cli.run_invocation_via_bridge",
                side_effect=RuntimeError("tmux missing"),
            ):
                with patch(
                    "tools.automation_runner.cli.run_invocation_streaming",
                    return_value=runner_cli.RuntimeResult(command=["codex", "exec"], output_path=log_path),
                ) as direct_run:
                    result = adapter.run(
                        agent_id="frontend-squad",
                        workflow_id="prompt-runtime-test",
                        state_name="L3_DEVELOP",
                        prompt="hello",
                        log_path=log_path,
                        use_search=False,
                        event_callback=events.append,
                    )
        direct_run.assert_called_once()
        self.assertEqual(result.output_path, log_path)
        self.assertTrue(any(event.get("kind") == "runtime_bridge_unavailable" for event in events))

    def test_bridge_invocation_strips_codex_output_flag(self) -> None:
        log_path = self.workspace_dir / "bridge-strip.log"
        invocation = runner_cli.RuntimeInvocation(
            command=["codex", "exec", "--full-auto", "-C", str(self.workspace_dir), "-o", str(log_path), "reply OK"],
            env=os.environ.copy(),
            cwd=str(self.workspace_dir),
        )
        with patch("tools.runtime_bridge.cli.submit_via_bridge") as submit:
            submit.return_value = SimpleNamespace(command=["codex", "exec"], output_path=log_path, exit_code=0)
            result = runner_cli.run_invocation_via_bridge(
                invocation=invocation,
                runtime_name="codex",
                agent_id="frontend-squad",
                workflow_id="prompt-runtime-test",
                state_name="L3_DEVELOP",
                log_path=log_path,
            )
        bridge_command = submit.call_args.kwargs["command"]
        self.assertNotIn("-o", bridge_command)
        self.assertEqual(result.output_path, log_path)

    def test_runner_falls_back_to_alternate_runtime_after_silent_timeout(self) -> None:
        class SilentAdapter(runner_cli.RuntimeAdapter):
            name = "claude"

            def prepare(
                self,
                *,
                agent_id: str,
                workflow_id: str,
                state_name: str,
                prompt: str,
                log_path: Path,
                use_search: bool,
            ) -> runner_cli.RuntimeInvocation:
                raise AssertionError("prepare should not be called in this test")

            def run(
                self,
                *,
                agent_id: str,
                workflow_id: str,
                state_name: str,
                prompt: str,
                log_path: Path,
                use_search: bool,
                event_callback: runner_cli.EventCallback | None = None,
            ) -> runner_cli.RuntimeResult:
                raise runner_cli.RuntimeNoOutputError("claude", agent_id, state_name, 5)

        class FallbackAdapter(FakeAdapter):
            name = "codex"

        runner = runner_cli.AutomationRunner(
            adapter=SilentAdapter(),
            stop_before=set(),
            max_steps=10,
            allow_runtime_fallback=True,
        )
        summary = runner.bootstrap_summary("帮我调研一个项目并输出 PRD", workflow_id="prompt-runtime-test")
        self.assertEqual(summary["status"], "bootstrapped")
        route = runner.load_route("prompt-runtime-test")
        registry = control_plane.get_runtime_context("prompt-runtime-test")[1]
        events: list[dict[str, object]] = []
        with patch("tools.automation_runner.cli.available_runtimes", return_value=["claude", "codex"]), patch(
            "tools.automation_runner.cli.pick_adapter",
            side_effect=lambda name: FallbackAdapter() if name == "codex" else SilentAdapter(),
        ), patch("tools.control_plane.cli.git", side_effect=fake_git):
            result = runner.run_agent(
                "prompt-runtime-test",
                route,
                "L1_RESEARCH",
                "market-research",
                registry,
                event_callback=events.append,
            )
        self.assertEqual(result["runtime"], "codex")
        self.assertTrue(any(event.get("kind") == "runtime_fallback" for event in events))
        self.assertTrue((control_plane.workflow_root("prompt-runtime-test") / "l1-intelligence" / "market_report.md").exists())

    def test_dispatch_dry_run_outputs_shell_wait_pattern(self) -> None:
        runner = runner_cli.AutomationRunner(adapter=runner_cli.CodexRuntimeAdapter(), stop_before=set(), max_steps=10)
        summary = runner.bootstrap_summary("帮我开发一个聊天页面", workflow_id="build-mvp-test")
        self.assertEqual(summary["status"], "bootstrapped")
        state = control_plane.load_state("build-mvp-test")
        state["current_state"] = "L3_DEVELOP"
        route = runner.load_route("build-mvp-test")

        l2_dir = control_plane.workflow_root("build-mvp-test") / "l2-planning"
        l2_dir.mkdir(parents=True, exist_ok=True)
        (l2_dir / "PRD.md").write_text("# PRD\n", encoding="utf-8")
        (l2_dir / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
        control_plane.write_json(
            l2_dir / "task_breakdown.json",
            {
                "version": "1.0.0",
                "workflow_id": "build-mvp-test",
                "created_at": control_plane.utc_now(),
                "planning_mode": "l3_parallel_execution",
                "development_principles": [
                    "dry_first",
                    "parallel_by_default",
                    "contract_before_code",
                    "owned_write_scope",
                    "host_capability_enhancement",
                ],
                "parallel_execution": {"default_mode": "parallel_by_default", "max_parallel_agents": 2},
                "tasks": [
                    {
                        "id": "FE-1",
                        "title": "Build frontend shell",
                        "owner": "frontend-squad",
                        "stage": "L3_DEVELOP",
                        "depends_on": [],
                        "parallel_group": "ui-api",
                        "write_scope": [".aegis/runs/build-mvp-test/l3-dev/frontend/**"],
                        "acceptance_criteria": ["UI renders a bounded shell"],
                        "dry_reuse_targets": [".aegis/runs/build-mvp-test/l3-dev/frontend"],
                        "host_capability_needs": ["resolve_host_capability"],
                    },
                    {
                        "id": "BE-1",
                        "title": "Build backend shell",
                        "owner": "backend-squad",
                        "stage": "L3_DEVELOP",
                        "depends_on": [],
                        "parallel_group": "ui-api",
                        "write_scope": [".aegis/runs/build-mvp-test/l3-dev/backend/**"],
                        "acceptance_criteria": ["API shell responds"],
                        "dry_reuse_targets": [".aegis/runs/build-mvp-test/l3-dev/backend"],
                        "host_capability_needs": ["resolve_host_capability"],
                    },
                ],
            },
        )
        control_plane.write_json(
            l2_dir / "implementation-contracts.json",
            {
                "version": "1.0.0",
                "workflow_id": "build-mvp-test",
                "generated_at": control_plane.utc_now(),
                "contract_version": "1.0.0",
                "shared_interfaces": [],
                "owned_write_scopes": {
                    "frontend-squad": [".aegis/runs/build-mvp-test/l3-dev/frontend/**"],
                    "backend-squad": [".aegis/runs/build-mvp-test/l3-dev/backend/**"],
                },
                "integration_rules": {"required_before_parallel": ["contract_before_code"]},
                "change_control": {"owner": "user", "mode": "explicit_approval"},
            },
        )
        requirements_lock = {
            "version": "1.0.0",
            "workflow_id": "build-mvp-test",
            "source_stage": "L2_PLANNING",
            "locked_at": control_plane.utc_now(),
            "product_goal": "Produce a locked PRD for the request",
            "scope": {"in": ["PRD", "architecture", "task breakdown"], "out": ["implementation"]},
            "user_stories": [],
            "non_functional_requirements": [],
            "assumptions": [],
            "change_control": {"owner": "user", "mode": "explicit_approval"},
            "lock_hash": "",
        }
        requirements_lock["lock_hash"] = control_plane.compute_requirements_lock_hash(requirements_lock)
        control_plane.write_json(l2_dir / "requirements-lock.json", requirements_lock)
        state["requirements_lock_hash"] = requirements_lock["lock_hash"]
        control_plane.write_json(control_plane.state_path("build-mvp-test"), state)

        result = runner.dispatch_workers(
            "build-mvp-test",
            route=route,
            dry_run=True,
            runtime_choice=runner_cli.RuntimeChoice("codex", "test-selected codex"),
        )
        self.assertTrue(result["dry_run"])
        self.assertIn("&", result["shell_script"])
        self.assertIn("wait", result["shell_script"])
        self.assertEqual(len(result["agents"]), 2)
        self.assertEqual(result["runtime_rationale"], "test-selected codex")

    def test_choose_runtime_for_state_prefers_host_runtime_when_declared(self) -> None:
        with patch.dict(os.environ, {"AEGIS_HOST_RUNTIME": "claude"}, clear=False), patch(
            "tools.automation_runner.cli.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}",
        ):
            choice = runner_cli.choose_runtime_for_state(
                workflow_id=None,
                state_name="L2_PLANNING",
                requested_runtime="auto",
                for_dispatch=False,
            )
        self.assertEqual(choice.runtime, "claude")
        self.assertIn("AEGIS_HOST_RUNTIME", choice.rationale)

    def test_choose_runtime_for_dispatch_prefers_non_host_runtime_when_available(self) -> None:
        with patch.dict(os.environ, {"AEGIS_HOST_RUNTIME": "claude"}, clear=False), patch(
            "tools.automation_runner.cli.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}",
        ):
            choice = runner_cli.choose_runtime_for_state(
                workflow_id="build-mvp-test",
                state_name="L3_DEVELOP",
                requested_runtime="auto",
                for_dispatch=True,
            )
        self.assertEqual(choice.runtime, "codex")
        self.assertIn("non-host runtime", choice.rationale)


if __name__ == "__main__":
    unittest.main()
