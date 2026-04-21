import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.runtime_bridge import cli as runtime_bridge


class RuntimeBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-bridge-workspace-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def test_bridge_session_name_for_workspace_is_stable(self) -> None:
        one = runtime_bridge.bridge_session_name_for_workspace(self.workspace_dir)
        two = runtime_bridge.bridge_session_name_for_workspace(self.workspace_dir)
        self.assertEqual(one, two)
        self.assertTrue(one.startswith("aegis-"))

    def test_list_bridge_sessions_empty_when_not_initialized(self) -> None:
        sessions = runtime_bridge.list_bridge_sessions(workspace=self.workspace_dir)
        self.assertEqual(sessions, [])

    def test_bridge_command_for_logging_strips_matching_codex_output_flag(self) -> None:
        log_path = self.workspace_dir / "bridge.log"
        command = ["codex", "exec", "--full-auto", "-C", str(self.workspace_dir), "-o", str(log_path), "reply OK"]
        normalized = runtime_bridge.bridge_command_for_logging(command, log_path)
        self.assertEqual(normalized, ["codex", "exec", "--full-auto", "-C", str(self.workspace_dir), "reply OK"])

    def test_poll_log_recovers_after_truncation(self) -> None:
        log_path = self.workspace_dir / "truncate.log"
        request_id = "abc123"
        log_path.write_text("old-content-that-will-disappear\n", encoding="utf-8")

        class FakeClock:
            def __init__(self) -> None:
                self.current = 0.0

            def monotonic(self) -> float:
                self.current += 0.1
                return self.current

            def sleep(self, _seconds: float) -> None:
                log_path.write_text(f"{runtime_bridge.DONE_PREFIX}:{request_id}:0\n", encoding="utf-8")

        clock = FakeClock()
        with patch("tools.runtime_bridge.cli.time.monotonic", side_effect=clock.monotonic), patch(
            "tools.runtime_bridge.cli.time.sleep",
            side_effect=clock.sleep,
        ):
            exit_code = runtime_bridge._poll_log(
                log_path=log_path,
                request_id=request_id,
                idle_timeout_seconds=5,
            )
        self.assertEqual(exit_code, 0)
