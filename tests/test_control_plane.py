import io
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.control_plane import cli


def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


def init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "AEGIS Test"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "aegis@example.com"], check=True, capture_output=True, text=True)


class ControlPlaneReviewLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-workspace-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(self.workspace_dir)})
        self.env_patch.start()
        self.workflow = f"test-review-loop-{uuid.uuid4().hex[:8]}"
        cli.ensure_workspace_layout()
        self.workflow_root = cli.workflow_root(self.workflow)
        cli.initialize_workflow(self.workflow)

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def gate_dir(self) -> Path:
        return self.workflow_root / "l1-intelligence"

    def move_to_l1_review(self) -> None:
        cli.write_state_transition(self.workflow, "L1_RESEARCH")
        cli.write_state_transition(self.workflow, "L1_REVIEW")

    def write_loop_status(
        self,
        *,
        status: str,
        round_number: int,
        verdict: str,
        open_issues: list[str],
        closed_issues: list[str] | None = None,
        lgtm: bool = False,
    ) -> None:
        payload = {
            "workflow_id": self.workflow,
            "gate": "L1_REVIEW",
            "round": round_number,
            "status": status,
            "verdict": verdict,
            "open_issues": open_issues,
            "closed_issues": closed_issues or [],
            "lgtm": lgtm,
            "max_rounds": 3,
            "updated_at": cli.utc_now(),
        }
        cli.write_json(self.gate_dir() / "review-loop-status.json", payload)

    def write_review_artifacts(self, *, round_number: int) -> None:
        self.gate_dir().mkdir(parents=True, exist_ok=True)
        (self.gate_dir() / "gate-review-report.md").write_text("gate review\n", encoding="utf-8")
        (self.gate_dir() / f"review-round-{round_number}.md").write_text("round details\n", encoding="utf-8")

    def write_review_passed(self, reviewer: str = "research-qa-agent", score: float = 8.6) -> None:
        cli.write_json(
            self.gate_dir() / "review-passed.json",
            {
                "score": score,
                "reviewer": reviewer,
                "blockers": [],
                "suggestions": [],
                "approved_at": cli.utc_now(),
            },
        )

    def write_market_outputs(self) -> None:
        for name in ["market_report.md", "competitive_analysis.md", "tech_feasibility.md"]:
            (self.gate_dir() / name).write_text(f"{name}\n", encoding="utf-8")

    def test_write_state_rejects_illegal_jump(self) -> None:
        cli.write_state_transition(self.workflow, "L1_RESEARCH")
        with self.assertRaisesRegex(cli.ControlPlaneError, "illegal state transition"):
            cli.write_state_transition(self.workflow, "L3_DEVELOP")
        state = cli.load_state(self.workflow)
        self.assertEqual(state["current_state"], "L1_RESEARCH")
        self.assertEqual(len(state["history"]), 1)

    def test_review_fix_re_review_lgtm_flow(self) -> None:
        self.move_to_l1_review()
        self.write_review_artifacts(round_number=1)
        self.write_loop_status(
            status="changes_requested",
            round_number=1,
            verdict="changes_requested",
            open_issues=["RQ-1"],
        )

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            cli.post_agent_run("research-qa-agent", self.workflow)

        state = cli.load_state(self.workflow)
        self.assertEqual(state["next_state_hint"], "L1_RESEARCH")
        self.assertEqual(state["active_review_loop"]["status"], "changes_requested")

        cli.write_state_transition(self.workflow, "L1_RESEARCH")
        self.write_market_outputs()
        (self.gate_dir() / "fix-response-round-1.md").write_text("fixed RQ-1\n", encoding="utf-8")

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            cli.post_agent_run("market-research", self.workflow)

        state = cli.load_state(self.workflow)
        self.assertEqual(state["next_state_hint"], "L1_REVIEW")
        self.assertEqual(state["active_review_loop"]["status"], "re_review")

        cli.write_state_transition(self.workflow, "L1_REVIEW")
        self.write_review_artifacts(round_number=2)
        self.write_loop_status(
            status="lgtm",
            round_number=2,
            verdict="LGTM",
            open_issues=[],
            closed_issues=["RQ-1"],
            lgtm=True,
        )
        self.write_review_passed()

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            cli.post_agent_run("research-qa-agent", self.workflow)

        state = cli.load_state(self.workflow)
        self.assertIsNone(state["active_review_loop"])
        self.assertEqual(state["next_state_hint"], "L2_PLANNING")

        cli.write_state_transition(self.workflow, "L2_PLANNING")
        state = cli.load_state(self.workflow)
        self.assertEqual(state["current_state"], "L2_PLANNING")
        self.assertEqual(state["history"][-1]["to"], "L2_PLANNING")

    def test_review_passed_requires_lgtm(self) -> None:
        self.move_to_l1_review()
        self.write_review_artifacts(round_number=1)
        self.write_loop_status(
            status="changes_requested",
            round_number=1,
            verdict="changes_requested",
            open_issues=["RQ-2"],
        )
        self.write_review_passed()

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            with self.assertRaisesRegex(cli.ControlPlaneError, "review-passed.json must only exist after LGTM"):
                cli.post_agent_run("research-qa-agent", self.workflow)

    def test_blocked_transition_records_blocker(self) -> None:
        self.move_to_l1_review()
        self.write_review_artifacts(round_number=2)
        self.write_loop_status(
            status="blocked",
            round_number=2,
            verdict="blocked",
            open_issues=["RQ-CRITICAL-1"],
        )

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            cli.post_agent_run("research-qa-agent", self.workflow)

        state = cli.load_state(self.workflow)
        self.assertEqual(state["next_state_hint"], "BLOCKED")

        cli.write_state_transition(self.workflow, "BLOCKED")
        state = cli.load_state(self.workflow)
        self.assertEqual(state["current_state"], "BLOCKED")
        self.assertEqual(len(state["blockers"]), 1)
        self.assertEqual(state["blockers"][0]["state"], "L1_REVIEW")


class ControlPlaneDevelopmentGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-workspace-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(self.workspace_dir)})
        self.env_patch.start()
        self.workflow = f"test-dev-governance-{uuid.uuid4().hex[:8]}"
        cli.ensure_workspace_layout()
        self.workflow_root = cli.workflow_root(self.workflow)
        cli.initialize_workflow(self.workflow)
        state = cli.load_state(self.workflow)
        state["current_state"] = "L2_PLANNING"
        cli.write_json(cli.state_path(self.workflow), state)
        planning_dir = self.workflow_root / "l2-planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        for name in ["PRD.md", "architecture.md"]:
            (planning_dir / name).write_text(f"{name}\n", encoding="utf-8")
        cli.write_json(
            planning_dir / "requirements-lock.json",
            {
                "version": "1.0.0",
                "workflow_id": self.workflow,
                "source_stage": "L2_PLANNING",
                "locked_at": cli.utc_now(),
                "product_goal": "Ship a controlled build workflow",
                "scope": {"in": ["implementation"], "out": ["deployment"]},
                "user_stories": [],
                "non_functional_requirements": [],
                "assumptions": [],
                "change_control": {"owner": "user", "mode": "explicit_approval"},
                "lock_hash": "",
            },
        )

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def write_task_breakdown(self, frontend_scope: str, backend_scope: str) -> None:
        cli.write_json(
            self.workflow_root / "l2-planning" / "task_breakdown.json",
            {
                "version": "1.0.0",
                "workflow_id": self.workflow,
                "created_at": cli.utc_now(),
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
                        "title": "Frontend task",
                        "owner": "frontend-squad",
                        "stage": "L3_DEVELOP",
                        "depends_on": [],
                        "parallel_group": "ui-api",
                        "write_scope": [frontend_scope],
                        "acceptance_criteria": ["frontend works"],
                        "dry_reuse_targets": ["src/components", "src/lib"],
                        "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                    },
                    {
                        "id": "BE-1",
                        "title": "Backend task",
                        "owner": "backend-squad",
                        "stage": "L3_DEVELOP",
                        "depends_on": [],
                        "parallel_group": "ui-api",
                        "write_scope": [backend_scope],
                        "acceptance_criteria": ["backend works"],
                        "dry_reuse_targets": ["src/routes", "src/lib"],
                        "host_capability_needs": ["resolve_host_capability", "scan_repo_reuse"],
                    },
                ],
            },
        )

    def write_implementation_contracts(self, frontend_scope: str, backend_scope: str) -> None:
        cli.write_json(
            self.workflow_root / "l2-planning" / "implementation-contracts.json",
            {
                "version": "1.0.0",
                "workflow_id": self.workflow,
                "generated_at": cli.utc_now(),
                "contract_version": "1.0.0",
                "shared_interfaces": [],
                "owned_write_scopes": {
                    "frontend-squad": [frontend_scope],
                    "backend-squad": [backend_scope],
                },
                "integration_rules": {
                    "required_before_parallel": ["contract_before_code"],
                },
                "change_control": {"owner": "user", "mode": "explicit_approval"},
            },
        )

    def write_frontend_outputs(self) -> None:
        target = self.workflow_root / "l3-dev" / "frontend"
        target.mkdir(parents=True, exist_ok=True)
        (target / "README.md").write_text("frontend\n", encoding="utf-8")
        cli.write_json(
            target / "reuse-audit.json",
            {
                "version": "1.0.0",
                "workflow_id": self.workflow,
                "agent_id": "frontend-squad",
                "generated_at": cli.utc_now(),
                "requirements_lock_hash": cli.load_state(self.workflow)["requirements_lock_hash"],
                "completed_tasks": ["FE-1"],
                "scanned_existing_assets": ["src/components", "src/lib"],
                "reused_assets": [],
                "new_assets": ["src/app.tsx"],
                "duplication_risk_checks": ["No existing chat shell matched the locked requirements"],
                "host_capabilities_used": [
                    {
                        "action": "resolve_host_capability",
                        "resolution": "used mapped host planning capability only",
                    }
                ],
                "verification_commands": ["npm test"],
            },
        )

    def promote_to_l3(self) -> None:
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            cli.post_agent_run("prd-architect", self.workflow)
        cli.write_state_transition(self.workflow, "L2_REVIEW")
        gate_dir = self.workflow_root / "l2-planning"
        (gate_dir / "gate-review-report.md").write_text("ok\n", encoding="utf-8")
        (gate_dir / "review-round-1.md").write_text("ok\n", encoding="utf-8")
        cli.write_json(
            gate_dir / "review-loop-status.json",
            {
                "workflow_id": self.workflow,
                "gate": "L2_REVIEW",
                "round": 1,
                "status": "lgtm",
                "verdict": "LGTM",
                "open_issues": [],
                "closed_issues": [],
                "lgtm": True,
                "max_rounds": 3,
                "updated_at": cli.utc_now(),
            },
        )
        cli.write_json(
            gate_dir / "review-passed.json",
            {
                "score": 8.8,
                "reviewer": "research-qa-agent",
                "blockers": [],
                "suggestions": [],
                "approved_at": cli.utc_now(),
            },
        )
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            cli.post_agent_run("research-qa-agent", self.workflow)
        cli.write_state_transition(self.workflow, "L3_DEVELOP")

    def test_l2_planning_rejects_parallel_write_scope_conflict(self) -> None:
        self.write_task_breakdown(".aegis/runs/shared/**", ".aegis/runs/shared/**")
        self.write_implementation_contracts(".aegis/runs/shared/**", ".aegis/runs/shared/**")
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            with self.assertRaisesRegex(cli.ControlPlaneError, "parallel write scope conflict"):
                cli.post_agent_run("prd-architect", self.workflow)

    def test_l3_pre_run_requires_agent_assignment_and_contracts(self) -> None:
        self.write_task_breakdown(
            ".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow),
            ".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow),
        )
        self.write_implementation_contracts(
            ".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow),
            ".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow),
        )
        self.promote_to_l3()
        result = cli.pre_agent_run("frontend-squad", self.workflow)
        self.assertIn("pre-run validation passed", result[0])

    def test_l3_post_run_requires_reuse_audit(self) -> None:
        frontend_scope = ".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow)
        backend_scope = ".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow)
        self.write_task_breakdown(frontend_scope, backend_scope)
        self.write_implementation_contracts(frontend_scope, backend_scope)
        self.promote_to_l3()
        cli.pre_agent_run("frontend-squad", self.workflow)
        (self.workflow_root / "l3-dev" / "frontend").mkdir(parents=True, exist_ok=True)
        (self.workflow_root / "l3-dev" / "frontend" / "README.md").write_text("frontend\n", encoding="utf-8")
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            with self.assertRaisesRegex(cli.ControlPlaneError, "missing development governance artifact"):
                cli.post_agent_run("frontend-squad", self.workflow)
        self.write_frontend_outputs()
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            result = cli.post_agent_run("frontend-squad", self.workflow)
        self.assertTrue(any("committed workflow changes" in line or "no workflow changes" in line for line in result))


class ControlPlaneWorkspacePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-workspace-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(self.workspace_dir)})
        self.env_patch.start()
        cli.ensure_workspace_layout()

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def test_workspace_doctor_accepts_stricter_policy_and_agent_overrides(self) -> None:
        manifest = cli.load_json(cli.project_manifest_path())
        manifest["agent_overrides"] = {
            "backend-squad": {
                "project_context": "Current project is an Express service.",
                "extra_instructions": "Prefer existing repository utilities before adding dependencies.",
            }
        }
        manifest["review_policy"]["max_rounds"] = 2
        cli.write_json(cli.project_manifest_path(), manifest)

        cli.write_json(
            cli.agent_overrides_path(),
            {
                "version": "1.0.0",
                "agents": {
                    "backend-squad": {
                        "dependencies_add": ["contract:resolve_host_capability"],
                        "contract_actions_add": ["resolve_host_capability"],
                    }
                },
            },
        )
        cli.write_json(
            cli.workflow_policy_path(),
            {
                "version": "1.0.0",
                "gate_overrides": {
                    "L3_CODE_REVIEW": {
                        "min_score": 8.8,
                        "required_outputs_add": ["project-review-notes.md"],
                    }
                },
            },
        )

        result = cli.workspace_doctor()
        self.assertIn("workspace ready", result[-1])

        workflow = f"workspace-policy-{uuid.uuid4().hex[:8]}"
        cli.initialize_workflow(workflow)
        state = cli.load_state(workflow)
        state["workflow_type"] = "build"
        cli.write_json(cli.state_path(workflow), state)
        project_lock, registry, orchestrator, _ = cli.get_runtime_context(workflow)
        backend = cli.registry_by_id(registry)["backend-squad"]
        self.assertEqual(project_lock["review_policy"]["max_rounds"], 2)
        self.assertIn("Express service", backend["project_context"])
        self.assertIn("resolve_host_capability", backend["contract_actions"])
        self.assertIn("contract:resolve_host_capability", backend["dependencies"])
        self.assertEqual(orchestrator["gates"]["L3_CODE_REVIEW"]["min_score"], 8.8)
        self.assertEqual(orchestrator["gates"]["L3_CODE_REVIEW"]["review_loop"]["max_rounds"], 2)
        self.assertIn("project-review-notes.md", orchestrator["gates"]["L3_CODE_REVIEW"]["required_outputs"])

    def test_workspace_doctor_rejects_policy_that_weakens_core_gate(self) -> None:
        cli.write_json(
            cli.workflow_policy_path(),
            {
                "version": "1.0.0",
                "gate_overrides": {
                    "L3_CODE_REVIEW": {
                        "min_score": 7.0,
                    }
                },
            },
        )
        with self.assertRaisesRegex(cli.ControlPlaneError, "cannot be lower than the core minimum"):
            cli.workspace_doctor()


class ControlPlaneWorkspaceResolutionTests(unittest.TestCase):
    def test_attach_workspace_rejects_non_git_root(self) -> None:
        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-nongit-"))
        try:
            with patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(workspace_dir)}, clear=False):
                with self.assertRaisesRegex(cli.ControlPlaneError, "must be a git repository root"):
                    cli.ensure_workspace_layout()
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def test_hook_can_resolve_workspace_from_workflow_index(self) -> None:
        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-hook-workspace-"))
        try:
            init_git_workspace(workspace_dir)
            with patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(workspace_dir)}, clear=False):
                cli.ensure_workspace_layout()
                workflow = f"hook-workflow-{uuid.uuid4().hex[:8]}"
                cli.initialize_workflow(workflow)
                cli.write_state_transition(workflow, "L1_RESEARCH")
                gate_dir = cli.workflow_root(workflow) / "l1-intelligence"
                for name in ["market_report.md", "competitive_analysis.md", "tech_feasibility.md"]:
                    (gate_dir / name).write_text(f"{name}\n", encoding="utf-8")
            env = os.environ.copy()
            env.pop("AEGIS_WORKSPACE_ROOT", None)
            completed = subprocess.run(
                ["bash", str(cli.ROOT / ".aegis/hooks/pre-agent-run.sh"), "market-research", workflow],
                cwd=str(cli.ROOT),
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("pre-run validation passed", completed.stdout)
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def test_hook_fails_when_workflow_workspace_cannot_be_resolved(self) -> None:
        env = os.environ.copy()
        env.pop("AEGIS_WORKSPACE_ROOT", None)
        completed = subprocess.run(
            ["bash", str(cli.ROOT / ".aegis/hooks/pre-agent-run.sh"), "market-research", "missing-workflow"],
            cwd=str(cli.ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("failed to resolve workspace for workflow missing-workflow", completed.stderr)

    def test_write_gate_review_emits_valid_schema(self) -> None:
        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-gate-workspace-"))
        try:
            init_git_workspace(workspace_dir)
            with patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(workspace_dir)}, clear=False):
                cli.ensure_workspace_layout()
                workflow = f"gate-review-{uuid.uuid4().hex[:8]}"
                cli.initialize_workflow(workflow)
                state = cli.load_state(workflow)
                state["workflow_type"] = "research"
                state["current_state"] = "L1_REVIEW"
                cli.write_json(cli.state_path(workflow), state)
                result = cli.write_gate_review(
                    workflow=workflow,
                    gate_state="L1_REVIEW",
                    reviewer="research-qa-agent",
                    status="lgtm",
                    round_number=1,
                    score=8.7,
                    open_issues=[],
                    closed_issues=["RQ-1"],
                    blockers=[],
                    suggestions=["Looks good"],
                )
                self.assertTrue(any("review pass artifact" in line for line in result))
                gate_dir = cli.workflow_root(workflow) / "l1-intelligence"
                cli.validate_review_loop_status(
                    gate_dir / "review-loop-status.json",
                    workflow,
                    "L1_REVIEW",
                    cli.get_runtime_context(workflow)[2]["gates"]["L1_REVIEW"],
                )
                cli.validate_review_artifact(gate_dir / "review-passed.json", "research-qa-agent", 8.0)
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)


class ControlPlaneTeamPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-team-workspace-"))
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
        self.skills_patch = patch.object(cli, "SKILLS_DIR", self.skills_dir)
        self.commands_patch = patch.object(cli, "CLAUDE_COMMANDS_DIR", self.commands_dir)
        self.env_patch.start()
        self.skills_patch.start()
        self.commands_patch.start()
        cli.ensure_workspace_layout()

    def tearDown(self) -> None:
        self.commands_patch.stop()
        self.skills_patch.stop()
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        shutil.rmtree(self.team_home, ignore_errors=True)
        shutil.rmtree(self.skills_dir, ignore_errors=True)
        shutil.rmtree(self.commands_dir, ignore_errors=True)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(list(argv))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_create_global_team_pack_and_install_skill(self) -> None:
        result = cli.create_team_pack(
            team_id="AEGIS-video",
            display_name="AEGIS Video",
            mission="Long-lived team for video planning and editing direction.",
            domain="video-editing",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode=None,
            install=True,
        )
        self.assertTrue(any("created team pack" in line for line in result))
        manifest_path = self.team_home / "teams" / "global" / "AEGIS-video" / "team.json"
        payload = cli.load_json(manifest_path)
        self.assertEqual(payload["team_id"], "AEGIS-video")
        self.assertTrue(payload["host_integration"]["installed"])
        self.assertGreaterEqual(len(payload["roles"]), 4)
        self.assertEqual(payload["host_integration"]["skill_name"], "aegis-video")
        skill_target = self.skills_dir / "aegis-video"
        self.assertTrue(skill_target.is_symlink())
        self.assertEqual(skill_target.resolve(), manifest_path.parent.resolve())
        command_target = self.commands_dir / "aegis-video.md"
        self.assertTrue(command_target.is_symlink())
        self.assertEqual(command_target.resolve(), (manifest_path.parent / "COMMAND.md").resolve())
        doctor_result = cli.team_doctor("global")
        self.assertTrue(any("team pack valid" in line for line in doctor_result))

    def test_sync_agents_links_core_aegis_command(self) -> None:
        result = cli.ensure_skill_symlinks()
        self.assertTrue(any(line == "linked aegis" for line in result))
        self.assertTrue(any(line == "linked /aegis" for line in result))
        self.assertTrue((self.skills_dir / "aegis").is_symlink())
        command_target = self.commands_dir / "aegis.md"
        self.assertTrue(command_target.is_symlink())
        self.assertEqual(command_target.resolve(), (cli.ROOT / "agents" / "aegis" / "COMMAND.md").resolve())

    def test_create_project_team_pack_and_list_it(self) -> None:
        result = cli.create_team_pack(
            team_id="AEGIS-bugfix",
            display_name="AEGIS Bugfix",
            mission="Project-bound team for reproducing, fixing, and reviewing bugs.",
            domain="bug-fix",
            scope="project",
            role_specs=[],
            playbook_steps=[],
            review_mode="strict",
            install=False,
        )
        self.assertTrue(any("wrote team skill" in line for line in result))
        manifest_path = self.workspace_dir / ".aegis" / "teams" / "AEGIS-bugfix" / "team.json"
        payload = cli.load_json(manifest_path)
        self.assertEqual(payload["lifecycle_scope"], "project")
        listed = cli.list_team_packs("project")
        self.assertTrue(any("AEGIS-bugfix" in line for line in listed))
        shown = cli.show_team_pack("AEGIS-bugfix", "project")
        self.assertTrue(any("scope: project" in line for line in shown))

    def test_session_team_pack_cannot_install_persistently(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-session-lab",
            display_name="AEGIS Session Lab",
            mission="Temporary team for one-off experiments.",
            domain="research",
            scope="session",
            role_specs=[],
            playbook_steps=[],
            review_mode="lite",
            install=False,
        )
        with self.assertRaisesRegex(cli.ControlPlaneError, "session team packs cannot be installed"):
            cli.install_team_pack("AEGIS-session-lab", "session")

    def test_compose_team_pack_from_request_infers_video_team(self) -> None:
        result = cli.compose_team_pack_from_request(
            "AEGIS 帮我创建一个专业的视频剪辑团队，名字叫 AEGIS-video-pro，长期用于制作短视频",
            team_id=None,
            display_name=None,
            scope=None,
            install=False,
        )
        self.assertTrue(any("created team pack" in line for line in result))
        payload = cli.load_json(self.team_home / "teams" / "global" / "AEGIS-video-pro" / "team.json")
        self.assertEqual(payload["team_id"], "AEGIS-video-pro")
        self.assertEqual(payload["domain"], "video-editing")
        self.assertGreaterEqual(len(payload["roles"]), 4)

    def test_legacy_team_manifest_auto_migrates_to_memory_v2(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-legacy",
            display_name="AEGIS Legacy",
            mission="Legacy team manifest migration test.",
            domain="research",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        manifest_path = self.team_home / "teams" / "global" / "AEGIS-legacy" / "team.json"
        payload = cli.load_json(manifest_path)
        payload["memory_policy"] = {
            "retain_run_summaries": True,
            "store_team_learnings": True,
        }
        cli.write_json(manifest_path, payload)
        shown = cli.show_team_pack("AEGIS-legacy", "global")
        self.assertTrue(any("team_id: AEGIS-legacy" in line for line in shown))
        migrated = cli.load_json(manifest_path)
        self.assertIn("store_preference_memory", migrated["memory_policy"])
        self.assertIn("store_project_memory", migrated["memory_policy"])
        self.assertIn("semantic_recall", migrated["memory_policy"])

    def test_record_team_run_updates_memory_files(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-nx",
            display_name="AEGIS NX",
            mission="Long-lived team for reverse-engineering tasks.",
            domain="reverse-engineering",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="strict",
            install=True,
        )
        result = cli.record_team_run(
            team_id="AEGIS-nx",
            scope="global",
            request="Reverse target app and explain the login flow.",
            summary="Mapped the login flow and identified the likely token exchange path.",
            status="completed",
            artifacts=["report.md"],
            feedback=["Need deeper runtime validation next time."],
            learnings=["Token exchange patterns are easier to map when strings are indexed first."],
        )
        self.assertTrue(any("recorded team run" in line for line in result))
        team_dir = self.team_home / "teams" / "global" / "AEGIS-nx"
        summaries = cli.load_json(team_dir / "memory" / "run-summaries.json")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["status"], "completed")
        learnings = cli.load_json(team_dir / "memory" / "team-learnings.json")
        self.assertIn("Token exchange patterns are easier to map when strings are indexed first.", learnings)
        manifest = cli.load_json(team_dir / "team.json")
        self.assertEqual(manifest["run_count"], 1)
        memory_view = cli.show_team_memory("AEGIS-nx", "global")
        self.assertTrue(any("recent_runs:" in line for line in memory_view))
        self.assertTrue(any("memory_card_count:" in line for line in memory_view))
        doctor_result = cli.team_doctor("global")
        self.assertTrue(any("team pack valid" in line for line in doctor_result))

    def test_preference_and_project_memory_are_recalled_in_future_runs(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-memory",
            display_name="AEGIS Memory",
            mission="Long-lived team with durable memory.",
            domain="video-editing",
            scope="project",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        cli.record_team_preference(
            team_id="AEGIS-memory",
            scope="project",
            note="默认输出要先给 hook，再给完整脚本。",
            tags=["hook", "脚本"],
        )
        cli.record_team_project_memory(
            team_id="AEGIS-memory",
            scope="project",
            note="当前项目主要面向抖音竖屏短视频，默认优先 9:16 节奏。",
            tags=["抖音", "9:16"],
        )
        result = cli.prepare_team_run(
            team_id="AEGIS-memory",
            request="帮我做一个抖音短视频脚本，先把 hook 做强。",
            scope="project",
        )
        run_id = next(line for line in result if line.startswith("run_id: ")).split(": ", 1)[1]
        team_dir = self.workspace_dir / ".aegis" / "teams" / "AEGIS-memory"
        brief_payload = cli.load_json(team_dir / "runs" / f"{run_id}.brief.json")
        self.assertEqual(len(brief_payload["preference_memory"]), 1)
        self.assertEqual(len(brief_payload["project_memory"]), 1)
        self.assertGreaterEqual(len(brief_payload["relevant_memories"]), 2)
        brief_markdown = (team_dir / "runs" / f"{run_id}.brief.md").read_text(encoding="utf-8")
        self.assertIn("默认输出要先给 hook", brief_markdown)
        self.assertIn("当前项目主要面向抖音竖屏短视频", brief_markdown)
        memory_markdown = (team_dir / "memory" / "team-memory.md").read_text(encoding="utf-8")
        self.assertIn("Preference Memory", memory_markdown)
        self.assertIn("Project Memory", memory_markdown)

    def test_prepare_team_run_creates_brief_and_record_run_can_close_it(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-video",
            display_name="AEGIS Video",
            mission="Long-lived team for video planning and editing direction.",
            domain="video-editing",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        result = cli.prepare_team_run(
            team_id="AEGIS-video",
            request="做一个短视频方案，重点是风格、hook 和字幕节奏。",
            scope="global",
        )
        run_id_line = next(line for line in result if line.startswith("run_id: "))
        run_id = run_id_line.split(": ", 1)[1]
        team_dir = self.team_home / "teams" / "global" / "AEGIS-video"
        brief_path = team_dir / "runs" / f"{run_id}.brief.json"
        brief_markdown_path = team_dir / "runs" / f"{run_id}.brief.md"
        self.assertTrue(brief_path.exists())
        self.assertTrue(brief_markdown_path.exists())
        brief_payload = cli.load_json(brief_path)
        self.assertEqual(brief_payload["team_id"], "AEGIS-video")
        self.assertGreaterEqual(len(brief_payload["selected_roles"]), 3)
        shown_prepared = cli.show_team_run("AEGIS-video", run_id, "global")
        self.assertTrue(any("status: prepared" in line for line in shown_prepared))
        self.assertTrue(any("brief_markdown:" in line for line in shown_prepared))
        record_result = cli.record_team_run(
            team_id="AEGIS-video",
            scope="global",
            request="做一个短视频方案，重点是风格、hook 和字幕节奏。",
            summary="Delivered the first cut direction with hook and caption guidance.",
            status="completed",
            artifacts=["brief.md"],
            feedback=[],
            learnings=["Caption work should stay in the active role set when hook quality matters."],
            run_id=run_id,
        )
        self.assertTrue(any(f"removed team run brief: " in line for line in record_result))
        self.assertTrue(any(f"removed team run brief markdown: " in line for line in record_result))
        self.assertFalse(brief_path.exists())
        self.assertFalse(brief_markdown_path.exists())
        run_record = cli.load_json(team_dir / "runs" / f"{run_id}.json")
        summary_markdown_path = team_dir / "runs" / f"{run_id}.summary.md"
        memory_markdown_path = team_dir / "memory" / "team-memory.md"
        self.assertTrue(summary_markdown_path.exists())
        self.assertTrue(memory_markdown_path.exists())
        self.assertIn("Caption work should stay in the active role set", memory_markdown_path.read_text(encoding="utf-8"))
        self.assertEqual(run_record["run_id"], run_id)
        shown_completed = cli.show_team_run("AEGIS-video", run_id, "global")
        self.assertTrue(any("status: completed" in line for line in shown_completed))
        self.assertTrue(any("summary_markdown:" in line for line in shown_completed))
        doctor_result = cli.team_doctor("global")
        self.assertTrue(any("team pack valid" in line for line in doctor_result))

        next_result = cli.prepare_team_run(
            team_id="AEGIS-video",
            request="再做一个 hook 更强的版本。",
            scope="global",
        )
        next_run_id = next(line for line in next_result if line.startswith("run_id: ")).split(": ", 1)[1]
        next_brief = cli.load_json(team_dir / "runs" / f"{next_run_id}.brief.json")
        self.assertEqual(len(next_brief["recent_run_summaries"]), 1)
        self.assertEqual(len(next_brief["recent_learnings"]), 1)
        self.assertTrue(any("recent_runs_loaded: 1" in line for line in next_result))
        self.assertTrue(any("recent_learnings_loaded: 1" in line for line in next_result))

    def test_invoke_and_complete_team_run_support_cli_lifecycle(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-video-cli",
            display_name="AEGIS Video CLI",
            mission="Long-lived team for video planning and editing direction.",
            domain="video-editing",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        exit_code, stdout, stderr = self.run_cli(
            "invoke-team-pack",
            "--team",
            "AEGIS-video-cli",
            "--scope",
            "global",
            "--request",
            "做一个短视频方案，重点是开头 hook 和转场节奏。",
        )
        self.assertEqual(exit_code, 0, stderr)
        self.assertIn("ready_for_execution", stdout)
        run_id_line = next(line for line in stdout.splitlines() if line.startswith("run_id: "))
        run_id = run_id_line.split(": ", 1)[1]

        exit_code, stdout, stderr = self.run_cli(
            "show-team-run",
            "--team",
            "AEGIS-video-cli",
            "--scope",
            "global",
            "--run-id",
            run_id,
        )
        self.assertEqual(exit_code, 0, stderr)
        self.assertIn("status: prepared", stdout)

        exit_code, stdout, stderr = self.run_cli(
            "complete-team-run",
            "--team",
            "AEGIS-video-cli",
            "--scope",
            "global",
            "--run-id",
            run_id,
            "--summary",
            "Delivered a first-pass video direction with hook, pacing, and caption guidance.",
            "--artifact",
            "video-brief.md",
            "--learning",
            "Keep caption and structure roles active when the user asks for hook-heavy short videos.",
        )
        self.assertEqual(exit_code, 0, stderr)
        self.assertIn("recorded team run", stdout)
        self.assertIn("removed team run brief markdown", stdout)

        team_dir = self.team_home / "teams" / "global" / "AEGIS-video-cli"
        self.assertTrue((team_dir / "runs" / f"{run_id}.json").exists())
        self.assertTrue((team_dir / "runs" / f"{run_id}.summary.md").exists())

if __name__ == "__main__":
    unittest.main()
