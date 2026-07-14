"""custom_skills（文件夹 + SKILL.md 模型，渐进式披露）单元测试。"""

import os
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent import custom_skills


def _write_skill(root: Path, name: str, frontmatter: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


def _discover(path: Path):
    """把 custom_skills.settings 指向临时目录后重新发现。"""
    custom_skills.settings = types.SimpleNamespace(skills_dir=path)
    return custom_skills.discover_skills()


class TestCustomSkills(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_settings = custom_skills.settings
        self._orig_skills = custom_skills._SKILLS

    def tearDown(self) -> None:
        custom_skills.settings = self._orig_settings
        custom_skills._SKILLS = self._orig_skills

    def test_missing_dir_returns_empty(self) -> None:
        self.assertEqual(_discover(Path("/no/such/skills")), {})

    def test_discover_folder_skill_with_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_skill(
                root,
                "incident-triage",
                "name: incident-triage\ndescription: 事故分诊",
                "# SOP\n1. 第一步",
            )
            skills = _discover(root)
            self.assertIn("incident-triage", skills)
            meta = skills["incident-triage"]
            self.assertEqual(meta.description, "事故分诊")
            self.assertIn("第一步", meta.body)

    def test_load_skill_returns_full_body(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_skill(
                root, "deploy-check", "name: deploy-check\ndescription: 部署检查", "# Body\nstep-A"
            )
            custom_skills._SKILLS = _discover(root)
            ok = custom_skills.load_skill("deploy-check")
            self.assertEqual(ok["status"], "ok")
            self.assertIn("step-A", ok["instructions"])

            miss = custom_skills.load_skill("nope")
            self.assertEqual(miss["status"], "not_found")
            self.assertIn("deploy-check", miss["available"])

    def test_catalog_only_lists_name_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_skill(root, "s1", "name: s1\ndescription: D1", "# secret-body-should-not-appear")
            custom_skills._SKILLS = _discover(root)
            catalog = custom_skills.skills_catalog()
            self.assertIn("s1", catalog)
            self.assertIn("D1", catalog)
            # 渐进式披露：目录里不应包含正文。
            self.assertNotIn("secret-body-should-not-appear", catalog)

    def test_reference_files_listed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_skill(root, "with-ref", "name: with-ref\ndescription: R", "# Body")
            (root / "with-ref" / "reference").mkdir()
            (root / "with-ref" / "reference" / "thresholds.md").write_text("x", encoding="utf-8")
            skills = _discover(root)
            self.assertIn("thresholds.md", skills["with-ref"].reference_files)

    def test_folder_without_skill_md_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "not-a-skill").mkdir()
            (root / "_hidden").mkdir()
            self.assertEqual(_discover(root), {})

    def test_description_fallback_to_first_line(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # 无 description 字段，应回退取正文首个非空行。
            _write_skill(root, "nodesc", "name: nodesc", "# 首行标题\n正文")
            skills = _discover(root)
            self.assertEqual(skills["nodesc"].description, "首行标题")


if __name__ == "__main__":
    unittest.main()
