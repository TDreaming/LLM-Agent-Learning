#!/usr/bin/env bash
# DevOps 智能运维 Agent —— 一键安装脚本
#
# 作用：
#   1. 在 projects/ 下创建并激活 Python 虚拟环境（.venv）
#   2. 安装 requirements.txt 依赖
#   3. 若缺少 .env，则生成 .env 模板，提示填入模型密钥
#
# 用法（在仓库任意位置均可）：
#   bash projects/devops_agent/install.sh
#
# 要求：Python 3.12.x
set -euo pipefail

# 定位 projects/ 目录（脚本位于 projects/devops_agent/ 下）。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECTS_DIR}"

echo "==> 工作目录：${PROJECTS_DIR}"

# 1) 选择 Python 解释器（优先 python3.12）。
PY_BIN="$(command -v python3.12 || command -v python3 || command -v python || true)"
if [[ -z "${PY_BIN}" ]]; then
  echo "[错误] 未找到 Python，请先安装 Python 3.12.x" >&2
  exit 1
fi
PY_VER="$(${PY_BIN} -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
echo "==> 使用 Python：${PY_BIN} (版本 ${PY_VER})"
if [[ "${PY_VER}" != "3.12" ]]; then
  echo "[警告] 推荐 Python 3.12.x，当前为 ${PY_VER}，可能存在兼容性问题。"
fi

# 2) 创建虚拟环境（已存在则复用）。
if [[ ! -d ".venv" ]]; then
  echo "==> 创建虚拟环境 .venv"
  "${PY_BIN}" -m venv .venv
else
  echo "==> 已存在 .venv，跳过创建"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) 安装依赖。
echo "==> 升级 pip 并安装依赖"
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 4) 准备 .env。
if [[ ! -f ".env" ]]; then
  echo "==> 生成 .env 模板（请填入你的模型密钥）"
  cat > .env <<'EOF'
# 豆包（火山方舟）模型配置 —— 必填
MODEL_NAME=volcengine/doubao-seed-1-6-251015
ARK_API_KEY=替换为你的_API_Key

# 可选项（按需开启）
# DEVOPS_REQUIRE_APPROVAL=true
# DEVOPS_MAX_TOOL_CALLS=50
# DEVOPS_ENABLE_MCP=false
EOF
  echo "    已创建 ${PROJECTS_DIR}/.env —— 请编辑并填入 ARK_API_KEY"
else
  echo "==> 已存在 .env，跳过生成"
fi

echo ""
echo "✅ 安装完成！接下来："
echo "   cd ${PROJECTS_DIR}"
echo "   source .venv/bin/activate"
echo "   # 编辑 .env 填入 ARK_API_KEY 后，启动对话界面："
echo "   python -m devops_agent.cli"
