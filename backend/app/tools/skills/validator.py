"""
Skill Validator (Phase 4B).

Enforces strict structural and security validation for Orion reusable skills:
- Bounded step counts (1 to 10 steps).
- Known, registered Orion tools only.
- Structured arguments dictionaries only.
- Strict rejection of executable code, arbitrary SQL, shell command injection,
  recursive agent invocation, nested skills, and embedded 'confirmed' flags.
"""
import json
import re
from typing import Any

MAX_SKILL_STEPS = 10

# Prohibited tool names that attempt recursion or nesting
PROHIBITED_TOOLS = {
    "use_skill",
    "create_skill",
    "update_skill",
    "agent_run",
    "orchestrator",
    "chat",
    "plan",
    "ask_agent",
}

# Signatures of executable code
CODE_PATTERNS = [
    re.compile(r"\bdef\s+[a-zA-Z_]\w*\s*\(", re.IGNORECASE),
    re.compile(r"\bimport\s+[a-zA-Z_]", re.IGNORECASE),
    re.compile(r"\bfrom\s+[a-zA-Z_]+\s+import", re.IGNORECASE),
    re.compile(r"__import__\s*\(", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r"\bcompile\s*\(", re.IGNORECASE),
    re.compile(r"subprocess\.", re.IGNORECASE),
    re.compile(r"os\.system\s*\(", re.IGNORECASE),
    re.compile(r"os\.popen\s*\(", re.IGNORECASE),
    re.compile(r"__builtins__", re.IGNORECASE),
    re.compile(r"sys\.modules", re.IGNORECASE),
]

# Signatures of arbitrary SQL statements
SQL_PATTERNS = [
    re.compile(r"\bSELECT\s+.+\s+FROM\s+", re.IGNORECASE),
    re.compile(r"\bINSERT\s+INTO\s+", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\s+", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+.+\s+SET\s+", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\s+", re.IGNORECASE),
    re.compile(r"\bCREATE\s+TABLE\s+", re.IGNORECASE),
    re.compile(r"\bUNION\s+SELECT\s+", re.IGNORECASE),
]

# Shell operators that can be used for chaining or redirection
SHELL_OPERATORS = [";", "|", "&", "$", "`", "\n", "\r", ">", "<"]


class SkillValidator:
    """
    Validates skill workflow payloads against structural and security policies.
    """

    @classmethod
    def validate_workflow(
        cls,
        workflow: Any,
        registry: Any | None = None,
    ) -> dict[str, Any]:
        """
        Validate and normalize a skill workflow dictionary.

        Returns the validated workflow dictionary if valid.
        Raises ValueError if any rule is violated.
        """
        if isinstance(workflow, str):
            try:
                workflow = json.loads(workflow)
            except Exception as exc:
                raise ValueError(f"Workflow must be valid JSON: {exc}") from exc

        if not isinstance(workflow, dict):
            raise ValueError("Workflow must be a JSON object (dictionary).")

        if "steps" not in workflow:
            raise ValueError("Workflow must contain a 'steps' list.")

        steps = workflow["steps"]
        if not isinstance(steps, list):
            raise ValueError("Workflow 'steps' must be a list.")

        if len(steps) == 0:
            raise ValueError("Workflow must contain at least 1 step.")

        if len(steps) > MAX_SKILL_STEPS:
            raise ValueError(
                f"Workflow exceeds maximum allowed steps of {MAX_SKILL_STEPS} (found {len(steps)})."
            )

        known_tools: set[str] | None = None
        if registry is not None and hasattr(registry, "list_tools"):
            known_tools = {t["name"] for t in registry.list_tools()}

        validated_steps = []
        for idx, step in enumerate(steps, start=1):
            validated_step = cls._validate_step(step, idx, known_tools)
            validated_steps.append(validated_step)

        return {"steps": validated_steps}

    @classmethod
    def _validate_step(
        cls,
        step: Any,
        idx: int,
        known_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(step, dict):
            raise ValueError(f"Step {idx} must be a dictionary.")

        if "tool" not in step or not isinstance(step["tool"], str) or not step["tool"].strip():
            raise ValueError(f"Step {idx} missing valid 'tool' name.")

        tool_name = step["tool"].strip()

        # Reject nested skills
        if tool_name in {"use_skill", "create_skill", "update_skill"}:
            raise ValueError(
                f"Nested skills and skill management tools are not permitted in workflows (step {idx}: '{tool_name}')."
            )

        # Reject recursive agent invocation
        if tool_name in PROHIBITED_TOOLS:
            raise ValueError(
                f"Recursive agent invocation is not permitted in workflows (step {idx}: '{tool_name}')."
            )

        # Check tool registration
        if known_tools is not None and tool_name not in known_tools:
            raise ValueError(f"Unknown tool '{tool_name}' in step {idx}.")

        # Validate arguments
        if "arguments" not in step:
            raise ValueError(f"Step {idx} must contain an 'arguments' dictionary.")

        arguments = step["arguments"]
        if not isinstance(arguments, dict):
            raise ValueError(f"Step {idx} 'arguments' must be a dictionary.")

        # Reject 'confirmed': true
        if "confirmed" in arguments and bool(arguments["confirmed"]):
            raise ValueError(
                f"Step {idx} cannot specify 'confirmed': true. Confirmation is an application-level decision."
            )

        # Inspect argument values for executable code, SQL, shell injection
        cls._scan_arguments_security(arguments, tool_name, idx)

        return {
            "tool": tool_name,
            "arguments": arguments,
        }

    @classmethod
    def _scan_arguments_security(cls, arguments: dict[str, Any], tool_name: str, idx: int) -> None:
        """Scan arguments recursively for code, SQL, and shell command injection."""
        for key, val in arguments.items():
            if isinstance(val, str):
                # 1. Executable code check
                for pat in CODE_PATTERNS:
                    if pat.search(val):
                        raise ValueError(
                            f"Executable code detected in step {idx} argument '{key}': not permitted."
                        )

                # 2. Arbitrary SQL check
                for pat in SQL_PATTERNS:
                    if pat.search(val):
                        raise ValueError(
                            f"Arbitrary SQL detected in step {idx} argument '{key}': not permitted."
                        )

                # 3. Shell operator and allowlist check for run_command
                if tool_name == "run_command":
                    for op in SHELL_OPERATORS:
                        if op in val:
                            raise ValueError(
                                f"Shell operator '{op}' detected in step {idx} {key}: not permitted."
                            )
                    if key == "command":
                        try:
                            from ..command import ALLOWED_EXECUTABLES
                        except ImportError:
                            ALLOWED_EXECUTABLES = {"git", "python", "python3"}
                        parts = val.strip().split()
                        cmd_exe = parts[0].lower() if parts else ""
                        if cmd_exe not in ALLOWED_EXECUTABLES:
                            raise ValueError(
                                f"Command executable '{cmd_exe}' in step {idx} is not in Orion's command allowlist."
                            )

            elif isinstance(val, dict):
                cls._scan_arguments_security(val, tool_name, idx)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, (dict, str)):
                        if isinstance(item, str):
                            cls._scan_arguments_security({key: item}, tool_name, idx)
                        else:
                            cls._scan_arguments_security(item, tool_name, idx)
