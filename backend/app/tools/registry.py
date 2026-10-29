from typing import Any

from .audit import log_event
from .base import Tool
from .command import RunCommandTool
from .filesystem import (
    DeleteFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from .git import GitStatusTool
from .permissions import DEFAULT_TOOL_PERMISSIONS, Permission
from .personal_tools import (
    RecordDecisionTool,
    UpdateProjectTool,
    UpdateTaskTool,
)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)

        if tool is None:
            raise ValueError(f"Unknown tool '{name}'.")

        return tool

    def list_tools(self) -> list[dict[str, str]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permission": str(
                    DEFAULT_TOOL_PERMISSIONS.get(tool.name, tool.permission)
                ),
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self,
        name: str,
        /,
        confirmed: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Disallow caller/kwargs from overriding server confirmation status
        kwargs.pop("confirmed", None)

        tool = self.get(name)

        permission = DEFAULT_TOOL_PERMISSIONS.get(
            name,
            tool.permission,
        )

        if permission == Permission.BLOCKED:
            log_event(
                event="tool_execution",
                tool=name,
                arguments=kwargs,
                status="blocked",
            )
            raise PermissionError(
                f"Tool '{name}' is blocked by Orion's security policy."
            )

        if permission == Permission.CONFIRMATION_REQUIRED and not confirmed:
            log_event(
                event="tool_execution",
                tool=name,
                arguments=kwargs,
                status="confirmation_required",
            )
            raise PermissionError(
                f"Tool '{name}' requires user confirmation."
            )

        try:
            result = await tool.execute(**kwargs)

            log_event(
                event="tool_execution",
                tool=name,
                arguments=kwargs,
                result=result,
                status="success",
            )

            return result

        except Exception as exc:
            log_event(
                event="tool_execution",
                tool=name,
                arguments=kwargs,
                status="error",
                result={"error": str(exc)},
            )
            raise


def create_default_registry(personal_store: Any | None = None) -> ToolRegistry:
    from ..memory.personal import PersonalModelStore

    store = personal_store if personal_store is not None else PersonalModelStore()

    registry = ToolRegistry()

    registry.register(ListDirectoryTool())
    registry.register(ReadFileTool())
    registry.register(GitStatusTool())
    registry.register(WriteFileTool())
    registry.register(DeleteFileTool())
    registry.register(RunCommandTool())
    registry.register(UpdateProjectTool(store=store))
    registry.register(UpdateTaskTool(store=store))
    registry.register(RecordDecisionTool(store=store))

    from .skills import CreateSkillTool, UpdateSkillTool, UseSkillTool
    registry.register(CreateSkillTool(store=store, registry=registry))
    registry.register(UpdateSkillTool(store=store, registry=registry))
    registry.register(UseSkillTool(registry=registry, store=store))

    return registry
