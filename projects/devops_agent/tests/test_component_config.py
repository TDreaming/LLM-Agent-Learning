"""component_config（统一 YAML 配置解析）单元测试。"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent.component_config import (
    AgentConfigSnapshot,
    ConfigError,
    default_config_path,
    load_config,
)


def _write_tmp(text: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    f.write(text)
    f.close()
    return Path(f.name)


class TestComponentConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp: list[Path] = []

    def tearDown(self) -> None:
        for p in self._tmp:
            p.unlink(missing_ok=True)
        os.environ.pop("DEVOPS_AGENT_CONFIG", None)

    def _tmp_yaml(self, text: str) -> Path:
        p = _write_tmp(text)
        self._tmp.append(p)
        return p

    def test_parse_basic(self) -> None:
        p = self._tmp_yaml(
            """
agents:
  - name: diagnostics_agent
    enabled: true
  - name: communicator_agent
    enabled: false
tools:
  - name: load_skill
    enabled: true
mcp:
  - name: filesystem
    enabled: true
    args:
      root_dir: /tmp/rb
"""
        )
        snap = load_config(p)
        self.assertEqual(snap.enabled_names("agents"), ["diagnostics_agent"])
        self.assertEqual(snap.enabled_names("tools"), ["load_skill"])
        self.assertEqual(snap.enabled_names("mcp"), ["filesystem"])
        self.assertEqual(snap.mcp[0].args["root_dir"], "/tmp/rb")

    def test_missing_name_skipped(self) -> None:
        p = self._tmp_yaml(
            """
agents:
  - enabled: true
  - name: diagnostics_agent
    enabled: true
"""
        )
        snap = load_config(p)
        self.assertEqual([s.name for s in snap.agents], ["diagnostics_agent"])

    def test_wrong_enabled_type_treated_false(self) -> None:
        p = self._tmp_yaml(
            """
tools:
  - name: load_skill
    enabled: "yes"
"""
        )
        snap = load_config(p)
        self.assertEqual(snap.tools[0].enabled, False)

    def test_section_not_list_ignored(self) -> None:
        p = self._tmp_yaml("agents: not-a-list\n")
        snap = load_config(p)
        self.assertEqual(snap.agents, ())

    def test_empty_file_ok(self) -> None:
        p = self._tmp_yaml("")
        snap = load_config(p)
        self.assertIsInstance(snap, AgentConfigSnapshot)
        self.assertEqual(snap.agents, ())

    def test_invalid_yaml_raises(self) -> None:
        p = self._tmp_yaml("agents: [unclosed\n")
        with self.assertRaises(ConfigError):
            load_config(p)

    def test_root_not_mapping_raises(self) -> None:
        p = self._tmp_yaml("- just\n- a\n- list\n")
        with self.assertRaises(ConfigError):
            load_config(p)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(Path("/nonexistent/devops_agent_config_xyz.yaml"))

    def test_default_path_override(self) -> None:
        os.environ["DEVOPS_AGENT_CONFIG"] = "/some/custom/path.yaml"
        self.assertEqual(default_config_path(), Path("/some/custom/path.yaml"))

    def test_duplicate_name_keeps_first(self) -> None:
        p = self._tmp_yaml(
            """
tools:
  - name: load_skill
    enabled: true
  - name: load_skill
    enabled: false
"""
        )
        snap = load_config(p)
        self.assertEqual(len(snap.tools), 1)
        self.assertTrue(snap.tools[0].enabled)


if __name__ == "__main__":
    unittest.main()
