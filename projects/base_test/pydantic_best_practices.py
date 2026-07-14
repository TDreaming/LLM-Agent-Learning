"""Pydantic V2 最佳实践演示（可执行）。

研究对象：`from pydantic import BaseModel, Field, validator, Extra`

核心结论
--------
当前环境为 Pydantic V2（2.13.x）。在 V2 中：
  - `BaseModel` / `Field` 仍是核心 API，但用法升级（ConfigDict、Annotated、default_factory…）。
  - `validator`  已【废弃】 → 应使用 `field_validator`（单字段）+ `model_validator`（跨字段）。
  - `Extra`      已【废弃】 → 应使用 `model_config = ConfigDict(extra="forbid"|"ignore"|"allow")`。

本文件通过日志在“关键解释路径”打点，运行后可直接观察验证 / 序列化 / 废弃告警的真实行为。
运行：  python pydantic_best_practices.py
"""

from __future__ import annotations

import logging
import sys
import warnings
from typing import Annotated

# 同时导入「旧 API」与「新 API」，用于对照演示二者差异与废弃行为。
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# 日志配置：统一输出到 stdout（StreamHandler），符合云原生可观测规范。
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("pydantic.bp")

# 让 Pydantic 的 DeprecationWarning 始终显示（默认可能被过滤），用于“眼见为实”地看到废弃告警。
warnings.simplefilter("always", DeprecationWarning)


def banner(title: str) -> None:
    """打印分节标题，方便在终端定位每个演示阶段。"""
    log.info("=" * 72)
    log.info("# %s", title)
    log.info("=" * 72)


# ===========================================================================
# 演示 1：Field —— 声明式约束 vs 手写 property/setter
# ---------------------------------------------------------------------------
# 原理：BaseModel 在【类创建期】通过元类扫描类型注解 + Field 元数据，编译出一个
#       基于 pydantic-core（Rust）的高性能校验器（validator schema）。
#       实例化时由 Rust 核心一次性完成解析、强转(coercion)与校验，
#       因此无需像普通类那样为每个字段手写 property/setter。
# ===========================================================================
class AgentConfig(BaseModel):
    # 最佳实践：用 ConfigDict 取代 V1 的 `class Config` 和 `Extra` 枚举。
    #   extra="forbid"        -> 传入未声明字段直接报错（防止拼写错误静默吞掉，强约束首选）
    #   str_strip_whitespace  -> 自动去除字符串首尾空白
    #   frozen=False          -> 是否不可变（True 时实例 hashable 且禁止再赋值）
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,  # 关键：赋值时也触发校验（替代手写 setter 的核心收益）
    )

    # 最佳实践：用 Annotated[type, Field(...)] 表达「类型 + 约束」，比把约束塞进默认值更清晰。
    name: Annotated[str, Field(min_length=1, max_length=32, description="Agent 名称")]
    model: Annotated[str, Field(min_length=1, description="底层模型标识")]
    # 数值约束：ge/le 替代手写 if 判断；description 会进入 JSON Schema。
    temperature: Annotated[float, Field(ge=0.0, le=2.0, description="采样温度")] = 0.7
    # 可变默认值【必须】用 default_factory，否则所有实例共享同一个 list（经典陷阱）。
    tools: list[str] = Field(default_factory=list, description="工具名列表")
    # alias：对外用驼峰、对内用蛇形；需配合 populate_by_name 或按别名传入。
    max_tokens: int = Field(default=1024, ge=1, alias="maxTokens")

    # -------------------------------------------------------------------
    # 演示 2：field_validator —— 取代 V1 的 @validator
    # 原理：field_validator 注册到「字段级校验链」。
    #   mode="before"：在类型强转【之前】拿到原始输入（适合归一化、清洗）。
    #   mode="after" （默认）：在类型校验【之后】拿到已转型的值（适合业务规则）。
    # -------------------------------------------------------------------
    @field_validator("name", mode="after")
    @classmethod
    def _name_not_reserved(cls, v: str) -> str:
        log.info("[field_validator] 校验 name=%r", v)
        if v.lower() in {"none", "null", "system"}:
            raise ValueError(f"name 不能使用保留字: {v!r}")
        return v

    @field_validator("tools", mode="before")
    @classmethod
    def _coerce_tools(cls, v: object) -> object:
        # 归一化：允许用逗号分隔字符串传入，统一转成 list（before 模式的典型用途）。
        log.info("[field_validator before] tools 原始输入=%r (%s)", v, type(v).__name__)
        if isinstance(v, str):
            normalized = [t.strip() for t in v.split(",") if t.strip()]
            log.info("[field_validator before] tools 归一化为 %r", normalized)
            return normalized
        return v

    # -------------------------------------------------------------------
    # 演示 3：model_validator —— 跨字段 / 整体校验（V1 的 root_validator 升级版）
    # 原理：在所有字段校验完成后，对【整个模型实例】做联合约束。
    # -------------------------------------------------------------------
    @model_validator(mode="after")
    def _check_combo(self) -> "AgentConfig":
        log.info("[model_validator] 跨字段校验: temperature=%s, max_tokens=%s",
                 self.temperature, self.max_tokens)
        if self.temperature > 1.5 and self.max_tokens > 4096:
            raise ValueError("高 temperature 且高 max_tokens 组合不被允许")
        return self


def demo_happy_path() -> None:
    banner("演示 A：正常构造 + 各类最佳实践生效")
    cfg = AgentConfig(
        name="  test_agent  ",          # 首尾空白会被 str_strip_whitespace 清掉
        model="volcengine/doubao",
        temperature=0.9,
        tools="search, calculator, , clock",  # 字符串 -> before 校验器归一化为 list
        maxTokens=2048,                  # 用 alias 传入
    )
    log.info("构造成功: %r", cfg)
    # 最佳实践序列化：model_dump（dict）/ model_dump_json（str）取代 V1 的 .dict()/.json()。
    log.info("model_dump()        = %s", cfg.model_dump())
    log.info("model_dump(by_alias)= %s", cfg.model_dump(by_alias=True))
    log.info("model_dump_json()   = %s", cfg.model_dump_json())

    banner("演示 B：validate_assignment —— 赋值即校验（取代手写 setter）")
    cfg.temperature = 1.2
    log.info("赋值 temperature=1.2 成功 -> %s", cfg.temperature)
    try:
        cfg.temperature = 9.9  # 超出 le=2.0
    except ValidationError as e:
        log.warning("赋值非法值被拦截，错误数=%d：\n%s", e.error_count(), e)


def demo_validation_errors() -> None:
    banner("演示 C：校验失败的结构化错误（ValidationError）")
    try:
        AgentConfig(name="system", model="x")  # 命中保留字校验
    except ValidationError as e:
        log.warning("name 保留字被拦截：%s", e.errors()[0]["msg"])

    try:
        AgentConfig(name="ok", model="x", extra_field=123)  # extra="forbid"
    except ValidationError as e:
        log.warning("extra='forbid' 拦截未知字段：%s", e.errors()[0]["msg"])

    try:
        # 注意：max_tokens 设了 alias，且未开 populate_by_name，故必须用别名 maxTokens 传入，
        # 否则会先被 extra='forbid' 当成未知字段拦截，到不了跨字段校验。
        AgentConfig(name="ok", model="x", temperature=2.0, maxTokens=8000)  # 跨字段
    except ValidationError as e:
        log.warning("model_validator 跨字段约束触发：%s", e.errors()[0]["msg"])


# ===========================================================================
# 演示 4：为什么 validator / Extra 是“反面教材”——展示真实的废弃告警
# ---------------------------------------------------------------------------
# 原理：V2 仍提供 `validator`/`Extra` 的兼容垫片(shim)，但导入或使用时会触发
#       PydanticDeprecatedSince20 (DeprecationWarning)。最佳实践是迁移到新 API。
# ===========================================================================
def demo_deprecated_apis() -> None:
    banner("演示 D：旧 API（validator/Extra）触发的废弃告警 —— 应避免")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        # 注意：这里在函数内部 import，是为了【局部】捕获导入/定义期产生的告警。
        from pydantic import Extra, validator  # 旧 API，仅用于演示

        class LegacyConfig(BaseModel):
            class Config:           # V1 写法
                extra = Extra.allow  # 旧：等价于新写法 ConfigDict(extra="allow")

            name: str

            @validator("name")     # 旧：等价于新写法 @field_validator("name")
            def _v(cls, v):
                return v

        for w in caught:
            log.warning("捕获废弃告警: %s -> %s", w.category.__name__, w.message)
        if not caught:
            log.info("（本环境未抛出告警，但官方文档已标注其为 deprecated）")

    log.info("结论：用 field_validator/model_validator 取代 validator；"
             "用 ConfigDict(extra=...) 取代 Extra。")


def main() -> None:
    log.info("Pydantic 最佳实践演示启动")
    import pydantic
    log.info("当前 Pydantic 版本: %s", pydantic.VERSION)
    demo_happy_path()
    demo_validation_errors()
    demo_deprecated_apis()
    log.info("全部演示结束 ✔")


if __name__ == "__main__":
    main()
