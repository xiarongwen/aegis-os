from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tools.host_runtime import HostCliRequest, available_host_clis, get_host_cli_adapter


class HostRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path("/tmp/aegis-workspace")
        self.core_root = Path("/tmp/aegis-core")

    def test_codex_adapter_builds_exec_command(self) -> None:
        invocation = get_host_cli_adapter("codex").build_invocation(
            HostCliRequest(
                prompt="hello",
                workspace_root=self.workspace,
                core_root=self.core_root,
                output_path=self.workspace / "result.txt",
                use_search=True,
            )
        )
        self.assertEqual(
            invocation.command,
            [
                "codex",
                "--search",
                "exec",
                "--full-auto",
                "-C",
                str(self.workspace),
                "-o",
                str(self.workspace / "result.txt"),
                "hello",
            ],
        )
        self.assertEqual(invocation.env["AEGIS_WORKSPACE_ROOT"], str(self.workspace))
        self.assertEqual(invocation.env["AEGIS_CORE_ROOT"], str(self.core_root))

    def test_claude_adapter_builds_print_command(self) -> None:
        invocation = get_host_cli_adapter("claude").build_invocation(
            HostCliRequest(
                prompt="hello",
                workspace_root=self.workspace,
                core_root=self.core_root,
                extra_args=["--permission-mode", "bypassPermissions"],
            )
        )
        self.assertEqual(
            invocation.command,
            [
                "claude",
                "-p",
                "--bare",
                "--permission-mode",
                "bypassPermissions",
                "--output-format",
                "text",
                "--add-dir",
                str(self.workspace),
                "--add-dir",
                str(self.core_root),
                "hello",
            ],
        )

    def test_aider_and_opencode_share_same_request_shape(self) -> None:
        aider = get_host_cli_adapter("aider").build_invocation(
            HostCliRequest(prompt="fix bug", workspace_root=self.workspace, core_root=self.core_root, model="sonnet")
        )
        opencode = get_host_cli_adapter("opencode").build_invocation(
            HostCliRequest(prompt="fix bug", workspace_root=self.workspace, core_root=self.core_root, model="gpt-5")
        )
        self.assertEqual(aider.command, ["aider", "--message", "fix bug", "--model", "sonnet"])
        self.assertEqual(opencode.command, ["opencode", "run", "--model", "gpt-5", "fix bug"])

    def test_available_host_clis_respects_adapter_availability(self) -> None:
        with patch("tools.host_runtime.resolve_runtime_binary", side_effect=lambda name: f"/bin/{name}" if name in {"codex", "opencode"} else None):
            self.assertEqual(available_host_clis(["codex", "claude", "opencode"]), ["codex", "opencode"])


if __name__ == "__main__":
    unittest.main()
