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


if __name__ == "__main__":
    unittest.main()
