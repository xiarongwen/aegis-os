import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from tools.control_plane import cli


def fake_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


class ControlPlaneReviewLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = f"test-review-loop-{uuid.uuid4().hex[:8]}"
        self.workflow_root = cli.ROOT / "workflows" / self.workflow
        cli.initialize_workflow(self.workflow)

    def tearDown(self) -> None:
        shutil.rmtree(self.workflow_root, ignore_errors=True)

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
        self.workflow = f"test-dev-governance-{uuid.uuid4().hex[:8]}"
        self.workflow_root = cli.ROOT / "workflows" / self.workflow
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
        shutil.rmtree(self.workflow_root, ignore_errors=True)

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
        self.write_task_breakdown("workflows/shared/**", "workflows/shared/**")
        self.write_implementation_contracts("workflows/shared/**", "workflows/shared/**")
        with patch("tools.control_plane.cli.git", side_effect=fake_git):
            with self.assertRaisesRegex(cli.ControlPlaneError, "parallel write scope conflict"):
                cli.post_agent_run("prd-architect", self.workflow)

    def test_l3_pre_run_requires_agent_assignment_and_contracts(self) -> None:
        self.write_task_breakdown(
            "workflows/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow),
            "workflows/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow),
        )
        self.write_implementation_contracts(
            "workflows/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow),
            "workflows/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow),
        )
        self.promote_to_l3()
        result = cli.pre_agent_run("frontend-squad", self.workflow)
        self.assertIn("pre-run validation passed", result[0])

    def test_l3_post_run_requires_reuse_audit(self) -> None:
        frontend_scope = "workflows/{workflow}/l3-dev/frontend/**".replace("{workflow}", self.workflow)
        backend_scope = "workflows/{workflow}/l3-dev/backend/**".replace("{workflow}", self.workflow)
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

if __name__ == "__main__":
    unittest.main()
