from enum import StrEnum


class Permission(StrEnum):
    AUTOMATIC = "automatic"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"


DEFAULT_TOOL_PERMISSIONS = {
    "list_directory": Permission.AUTOMATIC,
    "read_file": Permission.AUTOMATIC,
    "git_status": Permission.AUTOMATIC,
    "write_file": Permission.CONFIRMATION_REQUIRED,
    "run_command": Permission.CONFIRMATION_REQUIRED,
    "delete_file": Permission.CONFIRMATION_REQUIRED,
}
