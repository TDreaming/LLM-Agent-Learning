---
name: incident-triage
description: 当用户报告某服务异常/告警、需要按标准流程做初步事故分诊（triage）时使用，产出现象、影响面、初步根因与下一步建议。
---

# 事故分诊 SOP（Incident Triage）

当用户报告某服务出现异常或告警时，按以下标准步骤进行初步分诊：

1. **确认目标**：明确受影响的服务名与时间范围；若缺失，用 `ask_user` 澄清。
2. **查健康**：委派 diagnostics 调用 `check_service_health(service)`，确认实例/副本与资源状态。
3. **看指标**：用 `query_metrics` 查看关键指标（latency / error_rate / qps）是否偏离基线。
4. **查日志**：用 `search_logs` 检索 error / timeout / exception 等关键词，定位异常线索。
5. **关联部署**：用 `get_deploy_status` 检查近期是否有发布/变更，判断是否变更引入。
6. **产出结论**：交由 communicator 汇总为结构化【事件摘要】：
   - 现象 / 影响范围 / 初步根因 / 已采取动作 / 下一步建议。
7. **处置建议**：若需回滚等写操作，提示走 `rollback_deploy` 的人工审批门，未获批不得执行。

> 注意：本 Skill 只定义「怎么做」的流程；具体动作由 Agent 调用既有工具完成。
> 更详细的判定阈值见 `reference/thresholds.md`。
