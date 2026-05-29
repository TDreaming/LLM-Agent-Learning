from . import works
from .local_memory import local_memory_service

root_agent = works.get_root_agent()

# 暴露给 ADK CLI / Runner 使用：
# - 通过 agent_loader 约定，模块级 `memory_service` 会被 ADK 识别并注入到 Runner。
memory_service = local_memory_service
