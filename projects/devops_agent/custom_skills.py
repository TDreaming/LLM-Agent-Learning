"""用户自定义 Skill（文件夹 + SKILL.md 模型）。

对齐业界 Agent Skills 标准（Claude Agent Skills / kagent skills）：每个 Skill 是 Skill
目录下的**一个子文件夹**，至少包含：

    skills/
      └── <skill-name>/
            ├── SKILL.md        # 必选：YAML frontmatter（name/description）+ 正文 SOP
            ├── reference/      # 可选：更详细的参考文档
            ├── scripts/        # 可选：可被 SOP 引用的脚本（如 Python）
            └── assets/         # 可选：图片/模板等资源

加载采用**渐进式披露（progressive disclosure）**：
- 启动时只扫描每个 SKILL.md 的 `name` + `description`，注入到 Agent 的「Skill 能力目录」，
  让模型知道「有哪些 Skill、各自适合干什么」，但不占用大量上下文；
- 模型判断需要某 Skill 时，调用 `load_skill(name)` 工具按需读取完整 SOP 正文
  （及可选的 reference 文件清单），再据此执行。

设计要点：
- 不要求用户写 Python 函数；Skill 即「文件夹 + Markdown SOP」。
- 解析失败/缺字段的 Skill 仅告警跳过，不影响 Agent 启动（优雅降级）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import settings

logger = logging.getLogger("devops_agent.custom_skills")

_SKILL_FILE = "SKILL.md"


@dataclass(frozen=True)
class SkillMeta:
    """一个 Skill 的元信息与正文。"""

    name: str
    description: str
    body: str
    path: Path

    @property
    def reference_files(self) -> list[str]:
        ref_dir = self.path / "reference"
        if not ref_dir.is_dir():
            return []
        return sorted(p.name for p in ref_dir.glob("**/*") if p.is_file())


def _parse_skill_md(md_path: Path) -> Optional[SkillMeta]:
    """解析单个 SKILL.md：YAML frontmatter（name/description）+ 正文。"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        logger.warning("skip skill %s (read error: %s)", md_path.parent.name, e)
        return None

    name: str = md_path.parent.name
    description: str = ""
    body: str = text

    # 解析 YAML frontmatter（以 --- 包裹，位于文件开头）。
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter, body = parts[1], parts[2].lstrip("\n")
            try:
                import yaml

                meta = yaml.safe_load(frontmatter) or {}
                if isinstance(meta, dict):
                    name = str(meta.get("name") or name)
                    description = str(meta.get("description") or "")
            except Exception as e:  # noqa: BLE001 - frontmatter 解析失败则降级用正文
                logger.warning("skill %s frontmatter parse failed: %s", name, e)

    if not description:
        # 缺 description 时，取正文首个非空行兜底。
        for line in body.splitlines():
            if line.strip():
                description = line.strip().lstrip("#").strip()
                break

    return SkillMeta(name=name, description=description, body=body, path=md_path.parent)


def discover_skills() -> dict[str, SkillMeta]:
    """扫描 Skill 目录，返回 {name: SkillMeta}；目录不存在时返回空。"""
    skills_dir = settings.skills_dir
    if not skills_dir.is_dir():
        logger.info("custom skills dir not found (%s); skipping.", skills_dir)
        return {}

    found: dict[str, SkillMeta] = {}
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_") or child.name.startswith("."):
            continue
        md_path = child / _SKILL_FILE
        if not md_path.is_file():
            continue
        meta = _parse_skill_md(md_path)
        if meta is None:
            continue
        if meta.name in found:
            logger.warning("duplicate skill name '%s'; keeping the first.", meta.name)
            continue
        found[meta.name] = meta
    logger.info("discovered %d custom skill(s) from %s", len(found), skills_dir)
    return found


# 启动时发现一次（渐进式披露的「目录」级信息）。
_SKILLS: dict[str, SkillMeta] = discover_skills()


def skills_catalog() -> str:
    """返回注入 Agent instruction 的「Skill 能力目录」文本（仅 name + description）。"""
    if not _SKILLS:
        return ""
    lines = ["[用户自定义 Skill 目录]（需要时用 load_skill(name) 读取完整步骤）"]
    for meta in _SKILLS.values():
        lines.append(f"- {meta.name}：{meta.description}")
    return "\n".join(lines)


def load_skill(name: str) -> dict[str, Any]:
    """按需加载某个自定义 Skill 的完整内容（SOP 正文 + 可选参考文件清单）。

    当某个 Skill 的能力与当前任务匹配时调用本工具，获取其详细执行步骤后再行动。

    Args:
        name: Skill 名称（来自「Skill 能力目录」）。

    Returns:
        含 name、description、instructions（SOP 正文）、reference_files 的字典；
        未找到时返回 status=not_found 及可用 Skill 列表。
    """
    meta = _SKILLS.get(name)
    if meta is None:
        return {
            "status": "not_found",
            "requested": name,
            "available": list(_SKILLS.keys()),
        }
    return {
        "status": "ok",
        "name": meta.name,
        "description": meta.description,
        "instructions": meta.body,
        "reference_files": meta.reference_files,
    }


def has_custom_skills() -> bool:
    return bool(_SKILLS)
