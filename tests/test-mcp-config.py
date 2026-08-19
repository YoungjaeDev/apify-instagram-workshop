import json
import subprocess
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_configured_server(command: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [command, *args, "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class McpConfigTest(unittest.TestCase):
    def assert_server_starts(self, command: str, args: list[str]) -> None:
        result = run_configured_server(command, args)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("mcpdoc", result.stdout)

    def test_claude_mcpdoc_command_starts(self) -> None:
        config = json.loads((REPO_ROOT / ".mcp.json").read_text())
        server = config["mcpServers"]["apify-docs"]
        self.assert_server_starts(server["command"], server["args"])

    def test_codex_mcpdoc_command_starts(self) -> None:
        with (REPO_ROOT / ".codex/config.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
        server = config["mcp_servers"]["apify_docs"]
        self.assert_server_starts(server["command"], server["args"])


if __name__ == "__main__":
    unittest.main()
