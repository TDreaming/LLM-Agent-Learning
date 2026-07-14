# AGENTS.md

## Repository Purpose

This repository records learning paths, notes, and resources related to LLMs, AI Agents, and related AI engineering topics. Alongside the knowledge base, it hosts two small, runnable Agent examples under `projects/` that contrast different agent frameworks. Treat it as both a documentation/knowledge-base repository and a hands-on example repository.

## Structure

- `README.md`: High-level repository introduction and how to run the examples.
- `learn/`: Main learning notes and curated resources.
  - `learn/LLMs/`: Notes focused on large language models (e.g. Anthropic Claude 101).
  - `learn/resources.md`: General resources, references, and the learning roadmap.
- `projects/`: Runnable Agent examples that compare frameworks.
  - `projects/base_chart_langgraph/`: A LangGraph ReAct chatbot example.
  - `projects/base_workflow_agent/`: A google-adk multi-stage Human-in-the-Loop workflow example.
  - `projects/devops_agent/`: An enterprise-grade google-adk DevOps/AIOps agent example.
  - `projects/requirements.txt`: Pinned dependencies (Python >=3.12,<3.13).
- `assets/`: Images used by the docs (e.g. the architecture whiteboard).
- `pyrightconfig.json`: Pyright/Pylance config pointing at the `projects/.venv` interpreter.

## Projects Overview

- `base_chart_langgraph`: Builds a `chatbot ⇄ tools` loop with `StateGraph`, routes via
  `tools_condition`, keeps context with `MemorySaver`, exposes the `sum_numbers` and
  `get_current_time` tools, and reaches the Doubao model through `ChatLiteLLM`. Entry: `agent.py`.
- `base_workflow_agent`: A custom `WorkflowAgent` drives a `spec → design → code → test` pipeline.
  Confirmation happens through the main chat input (reply `OK` to advance; any feedback re-runs the
  current stage with the original request + previous output + feedback). State is persisted via
  `session.state` (`EventActions.state_delta`), and `LocalFileMemoryService` stores memory in a
  local JSON file. The Doubao model is reached through `LiteLlm`. Entry: `agent.py`.
- `devops_agent`: An enterprise-grade DevOps/AIOps agent. A `devops_supervisor` root agent routes to
  three expert sub-agents (`diagnostics_agent` / `remediation_agent` / `communicator_agent`). Ops
  skills run through Ports & Adapters (`providers.py`, default read-only `MockAdapter`). Production
  guardrails (`guardrails.py`) gate dangerous/write ops behind an HITL approval token, feed rejection
  reasons back to the LLM, audit every tool call, and enforce a call budget. Structured stdout logging
  + audit (`observability.py`), persistent local-JSON memory (`memory.py`), and optional filesystem
  MCP (`mcp_tools.py`, graceful degradation). Reusable prompt fragments live in `prompts.py`.
  Component assembly (agents/tools/mcp enable-disable) is declared in a unified `agent_config.yaml`,
  parsed by `component_config.py`, wired via a `registry.py`, and **hot-reloaded** within 1s by a
  polling watcher (`hot_reload.py`) that mutates the running `root_agent` in place (secrets stay in
  `.env`). Supports both CLI (`adk run devops_agent` / `cli.py`) and conversational Web (`adk web`).
  Entry: `agent.py`.

## Editing Guidelines

- Prefer Markdown for all learning notes and documentation.
- Keep content concise, structured, and easy to scan.
- Use clear headings and short sections for long-form notes.
- Preserve existing Chinese content style unless a file is already written in English.
- When adding external references, include the source title and URL.
- Avoid adding generated build artifacts, caches, or temporary files.

## Code Conventions (projects/)

- Target Python >=3.12,<3.13; declare dependencies in `projects/requirements.txt` with PEP 508 markers.
- Keep the virtual environment and dependency files self-contained under `projects/`.
- Inside a package, use relative imports (e.g. `from . import works`); absolute imports break ADK loading.
- For ADK CLI (`adk run` / `adk web`) to auto-inject custom services, expose a module-level variable
  with the matching name (e.g. `memory_service`) in `agent.py`.
- Load secrets and model config from a `.env` file (`MODEL_NAME`, `ARK_API_KEY`); never commit them.

## Naming Conventions

- Use descriptive file names that reflect the topic.
- Prefer lowercase or readable title-style names consistently within the same directory.
- For topic-specific notes, place them under the most relevant subdirectory in `learn/`.

## Validation

- No formal build step is required for the docs.
- Before finishing changes, review Markdown formatting and links manually.
- For `projects/` changes, sanity-check imports and, where feasible, run the relevant example
  (`python base_chart_langgraph/agent.py` or `adk run base_workflow_agent`) with a configured `.env`.
- If tooling is added later, document the exact commands in `README.md` and update this file.

## Agent Instructions

- Do not reorganize existing notes unless explicitly requested.
- Do not delete or rewrite user-authored content without confirmation.
- Make minimal, focused changes for documentation updates.
- If a new section or directory convention is introduced, update this file to keep future agents aligned.
