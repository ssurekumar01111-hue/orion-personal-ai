from typing import Any

from .base import Tool
from .permissions import Permission
from .workspace import WORKSPACE_ROOT, is_protected_file, safe_path


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "List files and directories inside the Orion workspace."
    permission = Permission.AUTOMATIC

    async def execute(
        self,
        path: str = ".",
    ) -> dict[str, Any]:
        directory = safe_path(path)

        if not directory.exists():
            raise FileNotFoundError(
                f"Path does not exist: {path}"
            )

        if not directory.is_dir():
            raise NotADirectoryError(
                f"Path is not a directory: {path}"
            )

        entries = []

        for entry in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            entries.append(
                {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                }
            )

        return {
            "path": str(directory.relative_to(safe_path("."))),
            "entries": entries,
        }


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read the contents of a text file in the Orion workspace."
    permission = Permission.AUTOMATIC

    async def execute(
        self,
        path: str,
    ) -> dict[str, Any]:
        raw_path = WORKSPACE_ROOT / path
        if is_protected_file(raw_path):
            raise PermissionError(
                "Access to secret or environment files is forbidden."
            )

        file_path = safe_path(path)

        if is_protected_file(file_path):
            raise PermissionError(
                "Access to secret or environment files is forbidden."
            )

        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        if file_path.is_dir():
            raise IsADirectoryError(
                f"Path is a directory: {path}"
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"File is not valid UTF-8 text: {path}"
            ) from exc

        return {
            "path": str(file_path.relative_to(safe_path("."))),
            "content": content,
        }


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write content to a file in the Orion workspace (requires confirmation)."
    permission = Permission.CONFIRMATION_REQUIRED

    async def execute(
        self,
        path: str,
        content: str = "",
    ) -> dict[str, Any]:
        raw_path = WORKSPACE_ROOT / path
        if is_protected_file(raw_path):
            raise PermissionError(
                "Writing to secret or environment files is forbidden."
            )

        file_path = safe_path(path)

        if is_protected_file(file_path):
            raise PermissionError(
                "Writing to secret or environment files is forbidden."
            )

        if file_path.is_dir():
            raise IsADirectoryError(
                f"Path is a directory: {path}"
            )

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        return {
            "path": str(file_path.relative_to(safe_path("."))),
            "bytes_written": len(content.encode("utf-8")),
            "status": "written",
        }


class DeleteFileTool(Tool):
    name = "delete_file"
    description = (
        "Delete an individual regular file in the Orion workspace "
        "(requires confirmation)."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    async def execute(
        self,
        path: str,
    ) -> dict[str, Any]:
        raw_path = WORKSPACE_ROOT / path
        if is_protected_file(raw_path):
            raise PermissionError(
                "Deleting secret or environment files is forbidden."
            )

        file_path = safe_path(path)

        if file_path == WORKSPACE_ROOT:
            raise PermissionError(
                "Cannot delete the Orion workspace root."
            )

        if is_protected_file(file_path):
            raise PermissionError(
                "Deleting secret or environment files is forbidden."
            )

        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        if file_path.is_dir():
            raise IsADirectoryError(
                f"Cannot delete directory: {path}. delete_file only deletes individual files."
            )

        if not file_path.is_file():
            raise ValueError(
                f"Target is not a regular file: {path}"
            )

        file_path.unlink()

        return {
            "path": str(file_path.relative_to(safe_path("."))),
            "status": "deleted",
        }
