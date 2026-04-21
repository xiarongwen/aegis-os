import io
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.control_plane import cli


def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    if args[:2] == ("check-ignore", "-q"):
        return subprocess.CompletedProcess(["git", *args], 1, "", "")
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


class ControlPlaneWorkspaceRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-runtime-workspace-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(self.workspace_dir)})
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def test_ensure_workspace_layout_materializes_runtime_assets(self) -> None:
        cli.ensure_workspace_layout()
        self.assertTrue((self.workspace_dir / ".aegis" / "core" / "registry.json").exists())
        self.assertTrue((self.workspace_dir / ".aegis" / "core" / "orchestrator.yml").exists())
        self.assertTrue((self.workspace_dir / ".aegis" / "agents" / "market-research" / "SKILL.md").exists())
        self.assertTrue((self.workspace_dir / ".aegis" / "shared-contexts" / "tool-contracts.yml").exists())
        self.assertTrue((self.workspace_dir / ".aegis" / "hooks" / "pre-agent-run.sh").exists())
        self.assertTrue((self.workspace_dir / ".aegis" / "schedules" / "nightly-evolution.sh").exists())

        hook_content = (self.workspace_dir / ".aegis" / "hooks" / "pre-agent-run.sh").read_text(encoding="utf-8")
        self.assertIn("aegis ctl", hook_content)
        self.assertIn("run_control_plane", hook_content)

    def test_aegis_attach_workspace_from_subdirectory_uses_git_root(self) -> None:
        nested_dir = self.workspace_dir / "projects" / "app"
        nested_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.pop("AEGIS_WORKSPACE_ROOT", None)
        completed = subprocess.run(
            ["bash", str(cli.ROOT / "aegis"), "ctl", "attach-workspace"],
            cwd=str(nested_dir),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.workspace_dir / ".aegis" / "project.yml").exists())
        self.assertFalse((nested_dir / ".aegis" / "project.yml").exists())


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
        self.assertTrue(
            any(
                "committed workflow changes" in line
                or "no workflow changes" in line
                or "workflow changes are gitignored; skipping commit" in line
                for line in result
            )
        )

    def test_l3_post_run_normalizes_legacy_reuse_audit_shape(self) -> None:
        frontend_scope = ".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow)
        backend_scope = ".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow)
        self.write_task_breakdown(frontend_scope, backend_scope)
        self.write_implementation_contracts(frontend_scope, backend_scope)
        self.promote_to_l3()
        cli.pre_agent_run("frontend-squad", self.workflow)

        target = self.workflow_root / "l3-dev" / "frontend"
        target.mkdir(parents=True, exist_ok=True)
        (target / "README.md").write_text("frontend\n", encoding="utf-8")
        (target / "app.js").write_text("console.log('ok');\n", encoding="utf-8")
        cli.write_json(
            target / "reuse-audit.json",
            {
                "workflow_id": self.workflow,
                "agent": "frontend-squad",
                "task_id": "FE-1",
                "scanned_assets": [
                    {
                        "path": "src/legacy",
                        "reason": "checked for reuse",
                        "result": "none",
                    }
                ],
                "reused_assets": [],
                "duplication_risk_checks": ["created only scoped files"],
                "host_capabilities_used": [
                    {
                        "abstract_action": "resolve_host_capability",
                        "runtime_binding": "mapped host capability",
                        "evidence": "README.md",
                    }
                ],
            },
        )

        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            result = cli.post_agent_run("frontend-squad", self.workflow)

        payload = cli.load_json(target / "reuse-audit.json")
        self.assertTrue(
            any(
                "committed workflow changes" in line
                or "no workflow changes" in line
                or "workflow changes are gitignored; skipping commit" in line
                for line in result
            )
        )
        self.assertEqual(payload["agent_id"], "frontend-squad")
        self.assertEqual(payload["completed_tasks"], ["FE-1"])
        self.assertEqual(payload["scanned_existing_assets"], ["src/legacy"])
        self.assertEqual(payload["requirements_lock_hash"], cli.load_state(self.workflow)["requirements_lock_hash"])
        self.assertIn("app.js", payload["new_assets"])
        self.assertEqual(payload["host_capabilities_used"][0]["action"], "resolve_host_capability")
        self.assertIn("mapped host capability", payload["host_capabilities_used"][0]["resolution"])

    def test_post_agent_run_skips_commit_when_workflow_dir_is_gitignored(self) -> None:
        frontend_scope = ".aegis/runs/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow)
        backend_scope = ".aegis/runs/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow)
        self.write_task_breakdown(frontend_scope, backend_scope)
        self.write_implementation_contracts(frontend_scope, backend_scope)
        self.promote_to_l3()
        cli.pre_agent_run("frontend-squad", self.workflow)
        self.write_frontend_outputs()
        (self.workspace_dir / ".gitignore").write_text(".aegis/runs/\n", encoding="utf-8")

        result = cli.post_agent_run("frontend-squad", self.workflow)

        self.assertIn(f"workflow changes are gitignored; skipping commit for {self.workflow}", result)


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
        self.assertTrue(
            "failed to resolve workspace for workflow missing-workflow" in completed.stderr
            or "workflow state missing" in completed.stderr
        )

    def test_resolve_workspace_accepts_attached_workspace_for_new_workflow(self) -> None:
        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-new-workflow-workspace-"))
        try:
            init_git_workspace(workspace_dir)
            with patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(workspace_dir)}, clear=False):
                cli.ensure_workspace_layout()
            with patch.dict(os.environ, {}, clear=True):
                previous_cwd = Path.cwd()
                os.chdir(workspace_dir)
                try:
                    resolved = cli.resolve_workspace(workflow="brand-new-workflow")
                finally:
                    os.chdir(previous_cwd)
            self.assertEqual(resolved, workspace_dir.resolve())
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

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

    def test_workflow_snapshot_reports_runtime_choices_and_artifacts(self) -> None:
        from tools.control_plane import tui

        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-ui-workspace-"))
        try:
            init_git_workspace(workspace_dir)
            with patch.dict(
                os.environ,
                {
                    "AEGIS_WORKSPACE_ROOT": str(workspace_dir),
                    "AEGIS_HOST_RUNTIME": "claude",
                },
                clear=False,
            ):
                cli.ensure_workspace_layout()
                workflow = f"ui-workflow-{uuid.uuid4().hex[:8]}"
                cli.initialize_workflow(workflow)
                state = cli.load_state(workflow)
                state["current_state"] = "L3_DEVELOP"
                state["workflow_type"] = "build"
                state["next_state_hint"] = "L4_REVIEW"
                cli.write_json(cli.state_path(workflow), state)
                cli.write_json(
                    cli.workflow_root(workflow) / "intent-lock.json",
                    {
                        "normalized_goal": "Add a minimal login flow",
                    },
                )
                cli.write_json(cli.requirements_lock_path(workflow), {"requirements": []})
                with patch("tools.automation_runner.cli.available_runtimes", return_value=["codex", "claude"]):
                    snapshot = tui.build_workflow_snapshot(workflow)
            self.assertEqual(snapshot.workflow_id, workflow)
            self.assertEqual(snapshot.runtime, "claude")
            self.assertEqual(snapshot.dispatch_runtime, "codex")
            self.assertIn("host runtime", snapshot.runtime_rationale)
            self.assertIn("dispatch selected", snapshot.dispatch_rationale)
            artifacts = {label: present for label, present, _ in snapshot.artifacts}
            self.assertTrue(artifacts["intent lock"])
            self.assertTrue(artifacts["requirements lock"])
            self.assertFalse(artifacts["task breakdown"])
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def test_workflow_ids_are_sorted_by_updated_at_desc(self) -> None:
        from tools.control_plane import tui

        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-ui-index-workspace-"))
        try:
            init_git_workspace(workspace_dir)
            with patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(workspace_dir)}, clear=False):
                cli.ensure_workspace_layout()
                older = f"workflow-old-{uuid.uuid4().hex[:6]}"
                newer = f"workflow-new-{uuid.uuid4().hex[:6]}"
                cli.initialize_workflow(older)
                cli.initialize_workflow(newer)
                index_payload = cli.load_workflow_index()
                index_payload["workflows"][older]["updated_at"] = "2026-04-20T10:00:00Z"
                index_payload["workflows"][newer]["updated_at"] = "2026-04-20T11:00:00Z"
                cli.save_workflow_index(index_payload)
                ordered = tui.workflow_ids()
            self.assertIn(newer, ordered)
            self.assertIn(older, ordered)
            self.assertLess(ordered.index(newer), ordered.index(older))
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def test_tui_execute_new_request_uses_runner_auto_runtime(self) -> None:
        from tools.control_plane import tui

        with patch("tools.automation_runner.cli.choose_runtime_for_state", return_value=SimpleNamespace(runtime="codex", rationale="auto runtime")) as choose_runtime:
            with patch("tools.automation_runner.cli.pick_adapter", return_value=object()) as pick_adapter:
                with patch("tools.automation_runner.cli.AutomationRunner") as runner_cls:
                    with patch(
                        "tools.automation_runner.cli.summarize_with_runtime_choice",
                        side_effect=lambda payload, runtime_choice: {
                            **payload,
                            "runtime": runtime_choice.runtime,
                            "runtime_rationale": runtime_choice.rationale,
                        },
                    ):
                        runner = runner_cls.return_value
                        runner.bootstrap.return_value = ("wf-1", None)
                        runner.resume.return_value = {"workflow_id": "wf-1", "status": "finished"}
                        result = tui.execute_new_request("build login flow")
        choose_runtime.assert_called_once()
        pick_adapter.assert_called_once_with("codex")
        runner.bootstrap.assert_called_once_with("build login flow", event_callback=None)
        runner.resume.assert_called_once()
        self.assertEqual(result["workflow_id"], "wf-1")
        self.assertEqual(result["runtime"], "codex")

    def test_tui_execute_dispatch_uses_dispatch_runtime(self) -> None:
        from tools.control_plane import tui

        workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-ui-dispatch-workspace-"))
        try:
            init_git_workspace(workspace_dir)
            with patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(workspace_dir)}, clear=False):
                cli.ensure_workspace_layout()
                workflow = f"ui-dispatch-{uuid.uuid4().hex[:8]}"
                cli.initialize_workflow(workflow)
                with patch("tools.automation_runner.cli.choose_runtime_for_state", return_value=SimpleNamespace(runtime="codex", rationale="dispatch runtime")) as choose_runtime:
                    with patch("tools.automation_runner.cli.pick_adapter", return_value=object()) as pick_adapter:
                        with patch("tools.automation_runner.cli.AutomationRunner") as runner_cls:
                            runner = runner_cls.return_value
                            runner.dispatch_workers.return_value = {"workflow_id": workflow, "status": "workers_completed"}
                            result = tui.execute_dispatch(workflow, dry_run=True)
            choose_runtime.assert_called_once()
            pick_adapter.assert_called_once_with("codex")
            runner.dispatch_workers.assert_called_once()
            self.assertEqual(result["workflow_id"], workflow)
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def test_tui_summarizes_repetitive_agent_stderr_noise(self) -> None:
        from tools.control_plane import tui

        state = tui.AppState()
        state.timeline_lines = []

        tui._handle_stream_event(
            state,
            {
                "kind": "agent_output",
                "agent": "market-research",
                "source": "stderr",
                "text": "web search: site:threejs.org solar system example",
            },
        )
        tui._handle_stream_event(
            state,
            {
                "kind": "agent_output",
                "agent": "market-research",
                "source": "stderr",
                "text": "web search: site:nasa.gov solar system demo",
            },
        )

        self.assertEqual(state.timeline_lines, ["agent> market-research searching web sources"])

    def test_tui_summarizes_shell_trace_noise_and_keeps_real_stderr(self) -> None:
        from tools.control_plane import tui

        state = tui.AppState()
        state.timeline_lines = []

        tui._handle_stream_event(
            state,
            {
                "kind": "agent_output",
                "agent": "frontend-squad",
                "source": "stderr",
                "text": "exec",
            },
        )
        tui._handle_stream_event(
            state,
            {
                "kind": "agent_output",
                "agent": "frontend-squad",
                "source": "stderr",
                "text": "/bin/zsh -lc \"rg --files\"",
            },
        )
        tui._handle_stream_event(
            state,
            {
                "kind": "agent_output",
                "agent": "frontend-squad",
                "source": "stderr",
                "text": "succeeded in 0ms:",
            },
        )
        tui._handle_stream_event(
            state,
            {
                "kind": "agent_output",
                "agent": "frontend-squad",
                "source": "stderr",
                "text": "I have enough evidence to write the artifact.",
            },
        )

        self.assertEqual(
            state.timeline_lines,
            [
                "agent> frontend-squad running tool commands",
                "agent> frontend-squad scanning workspace and executing checks",
                "stderr> frontend-squad stderr: I have enough evidence to write the artifact.",
            ],
        )


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

    def test_explicit_preference_signal_auto_promotes_after_recording_run(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-video-memory",
            display_name="AEGIS Video Memory",
            mission="Long-lived team for video planning and editing direction.",
            domain="video-editing",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        request = "记住，以后都先给 hook，再给完整脚本。"
        prepared = cli.prepare_team_run(
            team_id="AEGIS-video-memory",
            request=request,
            scope="global",
        )
        run_id = next(line for line in prepared if line.startswith("run_id: ")).split(": ", 1)[1]
        self.assertTrue(any("preference_signals_detected: 1" in line for line in prepared))

        cli.record_team_run(
            team_id="AEGIS-video-memory",
            scope="global",
            request=request,
            summary="Delivered a hook-first brief and the full script afterwards.",
            status="completed",
            artifacts=["brief.md"],
            feedback=[],
            learnings=[],
            run_id=run_id,
        )
        team_dir = self.team_home / "teams" / "global" / "AEGIS-video-memory"
        preferences_payload = cli.load_json(team_dir / "memory" / "preferences.json")
        observations_payload = cli.load_json(team_dir / "memory" / "preference-observations.json")
        cards_payload = cli.load_json(team_dir / "memory" / "memory-cards.json")
        self.assertEqual(len(preferences_payload["preferences"]), 1)
        self.assertEqual(observations_payload["observations"][0]["status"], "promoted")
        self.assertEqual(observations_payload["observations"][0]["occurrences"], 1)
        self.assertTrue(any(item["kind"] == "preference" for item in cards_payload["cards"]))

        next_result = cli.prepare_team_run(
            team_id="AEGIS-video-memory",
            request="再做一个版本，hook 要更强。",
            scope="global",
        )
        next_run_id = next(line for line in next_result if line.startswith("run_id: ")).split(": ", 1)[1]
        next_brief = cli.load_json(team_dir / "runs" / f"{next_run_id}.brief.json")
        self.assertEqual(len(next_brief["preference_memory"]), 1)
        self.assertTrue(any("preference_observation_count: 1" in line for line in cli.show_team_memory("AEGIS-video-memory", "global")))

    def test_repeated_weak_preference_signal_promotes_after_second_run(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-video-repeat",
            display_name="AEGIS Video Repeat",
            mission="Long-lived team for video planning and editing direction.",
            domain="video-editing",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        first_request = "这次先给 hook，再给完整脚本。"
        first_prepare = cli.prepare_team_run(
            team_id="AEGIS-video-repeat",
            request=first_request,
            scope="global",
        )
        first_run_id = next(line for line in first_prepare if line.startswith("run_id: ")).split(": ", 1)[1]
        cli.record_team_run(
            team_id="AEGIS-video-repeat",
            scope="global",
            request=first_request,
            summary="Delivered the hook-first plan.",
            status="completed",
            artifacts=["brief.md"],
            feedback=[],
            learnings=[],
            run_id=first_run_id,
        )

        team_dir = self.team_home / "teams" / "global" / "AEGIS-video-repeat"
        first_preferences = cli.load_json(team_dir / "memory" / "preferences.json")
        first_observations = cli.load_json(team_dir / "memory" / "preference-observations.json")
        self.assertEqual(len(first_preferences["preferences"]), 0)
        self.assertEqual(first_observations["observations"][0]["occurrences"], 1)
        self.assertEqual(first_observations["observations"][0]["status"], "observed")

        second_request = "还是先给 hook，再给完整脚本。"
        second_prepare = cli.prepare_team_run(
            team_id="AEGIS-video-repeat",
            request=second_request,
            scope="global",
        )
        second_run_id = next(line for line in second_prepare if line.startswith("run_id: ")).split(": ", 1)[1]
        cli.record_team_run(
            team_id="AEGIS-video-repeat",
            scope="global",
            request=second_request,
            summary="Repeated the hook-first delivery order.",
            status="completed",
            artifacts=["brief-v2.md"],
            feedback=[],
            learnings=[],
            run_id=second_run_id,
        )

        second_preferences = cli.load_json(team_dir / "memory" / "preferences.json")
        second_observations = cli.load_json(team_dir / "memory" / "preference-observations.json")
        self.assertEqual(len(second_preferences["preferences"]), 1)
        self.assertEqual(second_observations["observations"][0]["occurrences"], 2)
        self.assertEqual(second_observations["observations"][0]["status"], "promoted")

        future_prepare = cli.prepare_team_run(
            team_id="AEGIS-video-repeat",
            request="做一个新版本。",
            scope="global",
        )
        future_run_id = next(line for line in future_prepare if line.startswith("run_id: ")).split(": ", 1)[1]
        future_brief = cli.load_json(team_dir / "runs" / f"{future_run_id}.brief.json")
        self.assertEqual(len(future_brief["preference_memory"]), 1)

    def test_one_off_weak_preference_signal_stays_as_observation(self) -> None:
        cli.create_team_pack(
            team_id="AEGIS-video-observe",
            display_name="AEGIS Video Observe",
            mission="Long-lived team for video planning and editing direction.",
            domain="video-editing",
            scope="global",
            role_specs=[],
            playbook_steps=[],
            review_mode="standard",
            install=False,
        )
        request = "这次先给 hook，再给完整脚本。"
        prepared = cli.prepare_team_run(
            team_id="AEGIS-video-observe",
            request=request,
            scope="global",
        )
        run_id = next(line for line in prepared if line.startswith("run_id: ")).split(": ", 1)[1]
        cli.record_team_run(
            team_id="AEGIS-video-observe",
            scope="global",
            request=request,
            summary="Delivered the requested order for this run.",
            status="completed",
            artifacts=["brief.md"],
            feedback=[],
            learnings=[],
            run_id=run_id,
        )

        team_dir = self.team_home / "teams" / "global" / "AEGIS-video-observe"
        preferences_payload = cli.load_json(team_dir / "memory" / "preferences.json")
        observations_payload = cli.load_json(team_dir / "memory" / "preference-observations.json")
        self.assertEqual(len(preferences_payload["preferences"]), 0)
        self.assertEqual(len(observations_payload["observations"]), 1)
        self.assertEqual(observations_payload["observations"][0]["status"], "observed")
        memory_view = cli.show_team_memory("AEGIS-video-observe", "global")
        self.assertTrue(any("preference_observation_count: 1" in line for line in memory_view))
        self.assertTrue(any("preference_count: 0" in line for line in memory_view))

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


class ControlPlaneBridgeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-bridge-cli-workspace-"))
        init_git_workspace(self.workspace_dir)
        self.env_patch = patch.dict(os.environ, {"AEGIS_WORKSPACE_ROOT": str(self.workspace_dir)})
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def test_bridge_up_surfaces_clean_error(self) -> None:
        from tools.runtime_bridge import cli as runtime_bridge

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch(
            "tools.runtime_bridge.cli.ensure_bridge_session",
            side_effect=runtime_bridge.RuntimeBridgeError("tmux missing"),
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main(["bridge-up"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("tmux missing", stderr.getvalue())

if __name__ == "__main__":
    unittest.main()
