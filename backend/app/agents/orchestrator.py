import copy
import inspect
import json
import os
import re
from typing import Any

from ..config import get_settings
from ..memory.context import ContextEngine
from ..providers.router import ModelRouter
from ..tools.audit import log_event
from ..tools.confirmation import ConfirmationStore
from ..tools.permissions import DEFAULT_TOOL_PERMISSIONS, Permission
from ..tools.planner import (
    InspectionCompletionState,
    ToolPlanner,
    _normalize_dir_path,
)
from ..tools.registry import ToolRegistry


def _scrub_secrets(text: str) -> str:
    """Scrub known API keys and tokens from strings."""
    if not text:
        return text
    try:
        settings = get_settings()
        if settings.nebius_api_key and len(settings.nebius_api_key) > 3:
            text = text.replace(settings.nebius_api_key, "<REDACTED>")
        if settings.hermes_gateway_token and len(settings.hermes_gateway_token) > 3:
            text = text.replace(settings.hermes_gateway_token, "<REDACTED>")
        if settings.orion_demo_key and len(settings.orion_demo_key) > 3:
            text = text.replace(settings.orion_demo_key, "<REDACTED>")
    except Exception:
        pass

    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper()
        if any(term in k_upper for term in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            if k_upper not in ("PATH", "LANG", "LC_ALL") and len(env_v) > 4:
                if env_v in text:
                    text = text.replace(env_v, "<REDACTED>")

    text = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1<REDACTED>", text, flags=re.IGNORECASE)
    return text


def _sanitize_data(data: Any) -> Any:
    """Recursively scrub secrets from arguments, tool results, and observations."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_upper = str(k).upper()
            if any(term in k_upper for term in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")):
                sanitized[k] = "<REDACTED>"
            else:
                sanitized[k] = _sanitize_data(v)
        return sanitized
    elif isinstance(data, list):
        return [_sanitize_data(item) for item in data]
    elif isinstance(data, str):
        return _scrub_secrets(data)
    return data


class AgentOrchestrator:
    """
    Orchestrates the Orion bounded multi-step agent loop:

    Loop (max 5 iterations):
      user_message + previous observations
        → ToolPlanner (decide: tool or respond)
        → validate decision
        → permission check
        → if confirmation_required / blocked: stop immediately
        → if repeated identical tool call: stop immediately
        → ToolRegistry.execute (for automatic tools)
        → record observation
        → repeat or synthesize final response
    """

    MAX_ITERATIONS = 5

    def __init__(
        self,
        router: ModelRouter,
        registry: ToolRegistry,
        context_engine: ContextEngine,
        planner: ToolPlanner,
        confirmation_store: ConfirmationStore | None = None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.context_engine = context_engine
        self.planner = planner
        self.confirmation_store = confirmation_store or ConfirmationStore()

    @staticmethod
    def _format_confirmation_summary(tool_name: str, tool_args: dict[str, Any]) -> str:
        if tool_name == "update_task":
            op = tool_args.get("operation", "create")
            if op == "create":
                lines = [
                    "Orion wants to create this task:",
                    f"Title: {tool_args.get('title', '')}",
                ]
                if tool_args.get("description"):
                    lines.append(f"Description: {tool_args.get('description')}")
                lines.extend([
                    f"Status: {tool_args.get('status', 'todo')}",
                    f"Priority: {tool_args.get('priority', 'medium')}",
                ])
                if tool_args.get("project_id"):
                    lines.append(f"Project ID: {tool_args.get('project_id')}")
                if tool_args.get("goal_id"):
                    lines.append(f"Goal ID: {tool_args.get('goal_id')}")
                return "\n".join(lines)
            else:
                lines = [f"Orion wants to update task #{tool_args.get('task_id')}:"]
                for k, v in tool_args.items():
                    if k not in ("operation", "task_id"):
                        lines.append(f"{k.capitalize()}: {v}")
                return "\n".join(lines)

        elif tool_name == "update_project":
            op = tool_args.get("operation")
            if op == "create":
                lines = [
                    "Create project:",
                    f"Name: {tool_args.get('name', '')}",
                ]
                if tool_args.get("description"):
                    lines.append(f"Description: {tool_args.get('description')}")
                lines.append(f"Status: {tool_args.get('status', 'active')}")
                if tool_args.get("path"):
                    lines.append(f"Path: {tool_args.get('path')}")
                if tool_args.get("repository"):
                    lines.append(f"Repository: {tool_args.get('repository')}")
                return "\n".join(lines)
            elif op == "update":
                project_id = tool_args.get("project_id", "")
                lines = [f"Update project {project_id}:"]
                for k, v in tool_args.items():
                    if k not in ("operation", "project_id"):
                        lines.append(f"{k.capitalize()}: {v}")
                return "\n".join(lines)
            else:
                lines = ["Orion wants to modify project (operation unspecified or invalid):"]
                for k, v in tool_args.items():
                    lines.append(f"{k.capitalize()}: {v}")
                return "\n".join(lines)

        elif tool_name == "record_decision":
            decision = tool_args.get("decision")
            if not isinstance(decision, str) or not decision.strip():
                return "Orion wants to record a decision, but the decision text is missing or invalid."

            lines = [
                "Orion wants to record this decision:",
                f"Decision: {decision.strip()}",
            ]
            if tool_args.get("context"):
                lines.append(f"Context: {tool_args.get('context')}")
            if tool_args.get("project_id"):
                lines.append(f"Project ID: {tool_args.get('project_id')}")
            return "\n".join(lines)

        elif tool_name == "create_skill":
            wf = tool_args.get("workflow", {})
            if isinstance(wf, str):
                try:
                    wf = json.loads(wf)
                except Exception:
                    wf = {}
            steps_list = wf.get("steps", []) if isinstance(wf, dict) else []
            step_tools = [s.get("tool", "") for s in steps_list if isinstance(s, dict)]
            workflow_str = " -> ".join(step_tools) if step_tools else "None"
            lines = [
                "Orion wants to create this skill:",
                f"Name: {tool_args.get('name', '')}",
                f"Description: {tool_args.get('description', '')}",
                f"Workflow: {workflow_str}",
            ]
            return "\n".join(lines)

        elif tool_name == "update_skill":
            lines = [f"Orion wants to update skill #{tool_args.get('skill_id')}:"]
            for k, v in tool_args.items():
                if k not in ("operation", "skill_id"):
                    lines.append(f"{k.capitalize()}: {v}")
            return "\n".join(lines)

        elif tool_name == "write_file":
            return f"Orion wants to write to file: {tool_args.get('path', '')}"
        elif tool_name == "delete_file":
            return f"Orion wants to delete file: {tool_args.get('path', '')}"
        elif tool_name == "run_command":
            return f"Orion wants to execute command: {tool_args.get('command', '')}"

        return f"Arguments: {json.dumps(_sanitize_data(tool_args), indent=2, ensure_ascii=False)}"

    def _build_synthesis_messages(
        self,
        user_message: str,
        context: dict[str, Any],
        observations: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        memories = context.get("memories", [])
        personal_model = context.get("personal_model")
        base_prompt = self.context_engine.build_system_prompt(
            memories=memories,
            personal_model=personal_model,
        )

        system_content = (
            f"{base_prompt}\n\n"
            "Final Synthesis Guidelines:\n"
            "- Synthesize a concise, useful, and truthful response to the original user request based on the tool observations, Personal Model context, and conversation history.\n"
            "- Clearly distinguish between what Orion actually observed through tool executions versus what is stored in the Personal Model versus what was inferred.\n"
            "- Never claim that a Personal Model record was verified unless an executed tool actually verified it.\n"
            "- Explicitly state what remains incomplete or unverified if applicable.\n"
            "- Never fabricate actions, commands, files, or observations that were not executed."
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        prior_messages = context.get("messages", [])
        for i, msg in enumerate(prior_messages):
            if (
                i == len(prior_messages) - 1
                and msg.get("role") == "user"
                and msg.get("content") == user_message
            ):
                continue
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})

        obs_lines = []
        for obs in observations:
            step_num = obs.get("step", 1)
            tool_name = obs.get("tool", "unknown")
            safe_res = obs.get("result", {})
            obs_lines.append(
                f"[Step {step_num}]\nTool: {tool_name}\nResult:\n"
                f"{json.dumps(safe_res, indent=2, ensure_ascii=False)}"
            )
        formatted_obs = "\n\n".join(obs_lines)

        messages.append({
            "role": "assistant",
            "content": f"I executed {len(observations)} tool step(s) to gather observations.",
        })
        messages.append({
            "role": "user",
            "content": (
                f"The tool observations are as follows:\n\n{formatted_obs}\n\n"
                "Please provide a concise, natural-language response to the original request "
                "based on these observations. Distinguish what was actually observed from what was "
                "inferred, and note if anything remains incomplete."
            ),
        })

        return messages

    async def run(
        self,
        user_message: str,
        session_id: str | None = None,
        provider: str = "nebius",
    ) -> dict[str, Any]:
        """
        Run a bounded multi-step agent turn (up to 5 iterations):
          Each step:
            1. Call ToolPlanner with original user request + accumulated observations + personal context.
            2. If 'respond':
               - If no tools executed: direct conversational response with memory context.
               - If tools executed: synthesize final answer using observations + context.
               - Stop loop.
            3. If 'tool':
               - Validate tool registration and permission.
               - If blocked: stop loop immediately, return safe blocked response.
               - If confirmation_required: stop loop immediately, request user confirmation.
               - If repeated identical call: stop loop safely.
               - If automatic: execute via ToolRegistry.execute, record observation.
               - If iteration limit (5) reached: stop loop with limit reached message.

        Returns a structured dict with execution steps and backward-compatible fields.
        """
        available_tools = self.registry.list_tools()

        # Build context once at start of turn so all planner iterations and final synthesis share it
        context = self.context_engine.build_context(
            user_message=user_message,
            session_id=session_id,
        )

        steps: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        seen_tool_calls: set[tuple[str, str]] = set()

        completion_state = InspectionCompletionState(user_message)

        last_tool_decision: dict[str, Any] | None = None
        last_tool_used: str | None = None
        last_tool_args: dict[str, Any] | None = None
        last_tool_result: dict[str, Any] | None = None
        last_permission_status: str | None = None
        initial_decision: dict[str, Any] | None = None
        final_answer: str = ""
        model: str | None = None
        last_confirmation_id: str | None = None

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            if completion_state.is_complete(observations):
                steps.append({
                    "step": iteration,
                    "action": "respond",
                    "status": "completed",
                })
                synthesis_messages = self._build_synthesis_messages(
                    user_message=user_message,
                    context=context,
                    observations=observations,
                )
                llm_response = await self.router.chat(
                    messages=synthesis_messages,
                    provider=provider,
                )
                final_answer = (
                    llm_response["choices"][0]["message"].get("content") or ""
                )
                model = llm_response.get("model")
                break

            plan_kwargs: dict[str, Any] = {
                "user_message": user_message,
                "available_tools": available_tools,
                "provider": provider,
                "observations": observations if observations else None,
            }
            try:
                sig = inspect.signature(self.planner.plan)
                if "context" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                ):
                    plan_kwargs["context"] = context
            except (ValueError, TypeError):
                plan_kwargs["context"] = context

            decision = await self.planner.plan(**plan_kwargs)

            if initial_decision is None:
                initial_decision = decision

            # ── Branch A: planner chooses to respond ─────────────────────────
            if decision["action"] == "respond":
                steps.append({
                    "step": iteration,
                    "action": "respond",
                    "status": "completed",
                })

                if not observations:
                    messages = self.context_engine.build_messages(
                        user_message=user_message,
                        context=context,
                    )
                    llm_response = await self.router.chat(
                        messages=messages,
                        provider=provider,
                    )
                    final_answer = (
                        llm_response["choices"][0]["message"].get("content") or ""
                    )
                    model = llm_response.get("model")
                else:
                    synthesis_messages = self._build_synthesis_messages(
                        user_message=user_message,
                        context=context,
                        observations=observations,
                    )
                    llm_response = await self.router.chat(
                        messages=synthesis_messages,
                        provider=provider,
                    )
                    final_answer = (
                        llm_response["choices"][0]["message"].get("content") or ""
                    )
                    model = llm_response.get("model")

                break

            # ── Branch B: planner chooses a tool ─────────────────────────────
            tool_name: str = decision["tool"]
            tool_args: dict[str, Any] = copy.deepcopy(decision.get("arguments") or {})
            tool_args.pop("confirmed", None)

            # Validate tool is registered (raises ValueError if unknown)
            tool_obj = self.registry.get(tool_name)

            permission = DEFAULT_TOOL_PERMISSIONS.get(
                tool_name,
                tool_obj.permission,
            )
            permission_status = str(permission)
            last_permission_status = permission_status
            last_tool_decision = decision
            last_tool_used = tool_name
            last_tool_args = tool_args

            # BLOCKED check
            if permission == Permission.BLOCKED:
                steps.append({
                    "step": iteration,
                    "action": "tool",
                    "tool": tool_name,
                    "arguments": _sanitize_data(tool_args),
                    "permission": permission_status,
                    "status": "blocked",
                })
                final_answer = (
                    f"Tool '{tool_name}' is blocked by Orion's security policy "
                    "and cannot be executed."
                )
                break

            # CONFIRMATION_REQUIRED check
            if permission == Permission.CONFIRMATION_REQUIRED:
                pending = self.confirmation_store.create(
                    tool=tool_name,
                    arguments=tool_args,
                    session_id=session_id,
                )
                confirmation_id = pending.confirmation_id
                last_confirmation_id = confirmation_id

                log_event(
                    event="confirmation_requested",
                    tool=tool_name,
                    arguments=tool_args,
                    status="confirmation_required",
                    result={"confirmation_id": confirmation_id},
                )

                summary_str = self._format_confirmation_summary(tool_name, tool_args)

                steps.append({
                    "step": iteration,
                    "action": "tool",
                    "tool": tool_name,
                    "arguments": _sanitize_data(tool_args),
                    "permission": permission_status,
                    "status": "confirmation_required",
                    "confirmation_id": confirmation_id,
                })
                final_answer = (
                    f"Tool '{tool_name}' requires explicit user confirmation before it can run.\n\n"
                    f"{summary_str}\n\n"
                    f"Confirmation ID: {confirmation_id}\n"
                    "Please approve the action to proceed."
                )
                break

            # Repeated directory inspection guard (normalized path)
            if tool_name == "list_directory":
                norm_dir = _normalize_dir_path(tool_args.get("path"))
                if completion_state.is_dir_observed(norm_dir, observations):
                    steps.append({
                        "step": iteration,
                        "action": "tool",
                        "tool": tool_name,
                        "arguments": _sanitize_data(tool_args),
                        "permission": permission_status,
                        "status": "repeated_call",
                    })
                    final_answer = (
                        f"Loop terminated: Repeated directory inspection for '{norm_dir}' "
                        "is not permitted."
                    )
                    break

            # Repeated identical tool call guard
            call_key = (tool_name, json.dumps(tool_args, sort_keys=True))
            if call_key in seen_tool_calls:
                steps.append({
                    "step": iteration,
                    "action": "tool",
                    "tool": tool_name,
                    "arguments": _sanitize_data(tool_args),
                    "permission": permission_status,
                    "status": "repeated_call",
                })
                final_answer = (
                    f"Loop terminated: Repeated identical tool call '{tool_name}' "
                    "with identical arguments was detected."
                )
                break
            seen_tool_calls.add(call_key)

            # AUTOMATIC: Execute via ToolRegistry.execute
            try:
                raw_tool_result = await self.registry.execute(tool_name, **tool_args)
            except Exception as exc:
                steps.append({
                    "step": iteration,
                    "action": "tool",
                    "tool": tool_name,
                    "arguments": _sanitize_data(tool_args),
                    "permission": permission_status,
                    "status": "error",
                    "error": str(exc),
                })
                final_answer = f"Tool '{tool_name}' execution failed: {exc}"
                break

            safe_tool_result = _sanitize_data(raw_tool_result)
            last_tool_result = safe_tool_result

            obs_entry = {
                "step": iteration,
                "tool": tool_name,
                "arguments": _sanitize_data(tool_args),
                "result": safe_tool_result,
                "reason": decision.get("reason", ""),
            }
            observations.append(obs_entry)

            steps.append({
                "step": iteration,
                "action": "tool",
                "tool": tool_name,
                "arguments": _sanitize_data(tool_args),
                "permission": permission_status,
                "status": "executed",
            })

            # Record observation in session if active
            if session_id and hasattr(self.context_engine, "session_store"):
                try:
                    obs_summary = json.dumps(safe_tool_result, ensure_ascii=False)
                    self.context_engine.session_store.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=f"[Observation: {tool_name}] {obs_summary}",
                    )
                except Exception:
                    pass

            # Deterministic completion check after successful observation:
            if completion_state.is_complete(observations):
                synthesis_messages = self._build_synthesis_messages(
                    user_message=user_message,
                    context=context,
                    observations=observations,
                )
                llm_response = await self.router.chat(
                    messages=synthesis_messages,
                    provider=provider,
                )
                final_answer = (
                    llm_response["choices"][0]["message"].get("content") or ""
                )
                model = llm_response.get("model")
                break

            # Bounded limit reached on iteration 5
            if iteration == self.MAX_ITERATIONS:
                final_answer = (
                    "Bounded execution limit of 5 iterations was reached. "
                    "The task may be incomplete."
                )
                break

        planner_decision = (
            last_tool_decision if last_tool_decision is not None else initial_decision
        )

        result_payload: dict[str, Any] = {
            "response": final_answer,
            "planner_decision": planner_decision,
            "tool_used": last_tool_used,
            "tool_arguments": last_tool_args,
            "tool_result": last_tool_result,
            "permission_status": last_permission_status,
            "provider": provider,
            "model": model,
            "steps": steps,
        }
        if last_confirmation_id is not None:
            result_payload["confirmation_required"] = True
            result_payload["confirmation_id"] = last_confirmation_id

        return result_payload
