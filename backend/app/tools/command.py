"""
RunCommandTool — Security-first, confirmation-required workspace command execution
for the Orion personal AI project.

Isolation caveat
----------------
A sanitised environment and a dedicated working directory are process-level
controls, NOT an OS-level sandbox.  They prevent accidental disclosure of
secrets and restrict the working directory; they do NOT prevent a subprocess
from reading arbitrary files on the filesystem that the OS user can access.

For public-demo deployments, command execution tools must be disabled or
moved to a hardened sandbox runner (container / VM with no access to the
host filesystem or secrets).  See SECURITY.md for guidance.
"""
import os
import subprocess
from typing import Any

from .base import Tool
from .permissions import Permission
from .workspace import _get_workspace_root

# Conservative allowlist of permitted executable names
ALLOWED_EXECUTABLES = {"git", "python", "python3"}

# Prohibited shell wrapper executables
DISALLOWED_SHELL_WRAPPERS = {
    "bash", "sh", "zsh", "cmd", "powershell", "pwsh",
    "ksh", "csh", "tcsh", "dash", "busybox",
}

# Permitted read-only Git subcommands
GIT_ALLOWED_SUBCOMMANDS = {
    "status", "diff", "log", "branch", "show",
}

# Disallowed Git options that allow arbitrary code or command execution
GIT_DISALLOWED_PREFIXES = (
    "-c", "--config-env", "--exec-path", "--upload-pack", "--receive-pack",
)

# Prohibited shell metacharacters and sequences
DISALLOWED_METACHARACTERS = (
    ";", "&&", "||", "|", ">", ">>", "<", "$(", "`", "\n", "\r",
)

# Output bounds
MAX_OUTPUT_CHARS = 10_000

# Subprocess timeout bounds (seconds)
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 30.0

# Environment variable name fragments whose values must be excluded from
# the subprocess environment.
_SECRET_VAR_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

# Variables that contain these fragments but are safe to pass through.
_SAFE_PASSTHROUGH_VARS = frozenset({"PATH", "LANG", "LC_ALL"})

# Explicit list of known deployment secrets that must never appear in the
# child environment, regardless of naming convention.
_EXPLICIT_SECRET_VAR_NAMES = frozenset({
    "NEBIUS_API_KEY",
    "ORION_DEMO_KEY",
    "HERMES_GATEWAY_TOKEN",
})


def _scrub_secrets(text: str) -> str:
    """Scrub known API keys and tokens from strings."""
    if not text:
        return text
    try:
        from ..config import get_settings
        settings = get_settings()
        if settings.nebius_api_key and settings.nebius_api_key in text:
            text = text.replace(settings.nebius_api_key, "<REDACTED>")
        if settings.hermes_gateway_token and settings.hermes_gateway_token in text:
            text = text.replace(settings.hermes_gateway_token, "<REDACTED>")
        if settings.orion_demo_key and settings.orion_demo_key in text:
            text = text.replace(settings.orion_demo_key, "<REDACTED>")
    except Exception:
        pass
    return text


def _truncate_and_scrub(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate text to max_chars and scrub secrets."""
    if not text:
        return ""
    scrubbed = _scrub_secrets(text)
    if len(scrubbed) > max_chars:
        return scrubbed[:max_chars] + "\n...[output truncated]"
    return scrubbed


def _get_safe_env() -> dict[str, str]:
    """
    Return a sanitized copy of the environment without secret credentials.

    Explicitly removes:
      - NEBIUS_API_KEY, ORION_DEMO_KEY, HERMES_GATEWAY_TOKEN (by exact name)
      - Any variable whose name contains KEY, TOKEN, SECRET, PASSWORD, or
        CREDENTIAL (heuristic, excludes known safe variables like PATH).
    """
    safe_env = dict(os.environ)

    # Explicit removal by name (case-insensitive for the env key).
    for var in list(safe_env.keys()):
        if var.upper() in _EXPLICIT_SECRET_VAR_NAMES:
            safe_env.pop(var, None)

    # Heuristic removal.
    for var in list(safe_env.keys()):
        var_upper = var.upper()
        if var_upper in _SAFE_PASSTHROUGH_VARS:
            continue
        if any(frag in var_upper for frag in _SECRET_VAR_FRAGMENTS):
            safe_env.pop(var, None)

    return safe_env


def validate_command_policy(command: str, arguments: list[str]) -> None:
    """
    Validate that the requested command and arguments strictly adhere
    to Orion's command allowlist and security policy.
    """
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Command executable must be a non-empty string.")

    cmd_normalized = command.strip().lower()

    # Reject whitespace in executable name (prevents e.g. "git status" as executable)
    if " " in command or "\t" in command:
        raise ValueError(
            "Command executable must not contain whitespace. "
            "Pass executable in 'command' and separate tokens in 'arguments'."
        )

    # Check for shell wrappers
    if cmd_normalized in DISALLOWED_SHELL_WRAPPERS or any(
        w in cmd_normalized for w in ("sh", "bash", "powershell", "cmd")
    ):
        raise ValueError(
            f"Invocation of shell wrapper '{command}' is strictly prohibited."
        )

    # Check allowlist
    if cmd_normalized not in ALLOWED_EXECUTABLES:
        raise ValueError(
            f"Executable '{command}' is not in Orion's allowed command policy. "
            f"Permitted executables: {sorted(ALLOWED_EXECUTABLES)}"
        )

    if not isinstance(arguments, list):
        raise ValueError("'arguments' must be a list of string arguments.")

    for i, arg in enumerate(arguments):
        if not isinstance(arg, str):
            raise ValueError(f"Argument at index {i} is not a string: {arg!r}")

    # Check for prohibited shell metacharacters
    all_tokens = [command, *arguments]
    for token in all_tokens:
        for meta in DISALLOWED_METACHARACTERS:
            if meta in token:
                raise ValueError(
                    f"Command or argument contains prohibited shell character: '{meta}'"
                )

    # Command-specific policy checks
    if cmd_normalized == "git":
        if not arguments:
            raise ValueError("Git command requires a subcommand (e.g. ['status']).")

        # Check for dangerous flags
        for arg in arguments:
            if arg.startswith("!"):
                raise ValueError(f"Git alias/shell expansion is not permitted: '{arg}'")
            for prefix in GIT_DISALLOWED_PREFIXES:
                if (
                    arg == prefix
                    or arg.startswith(prefix + "=")
                    or (prefix.startswith("-c") and arg.startswith("-c"))
                ):
                    raise ValueError(f"Git option '{arg}' is not permitted.")

        # Find the first non-option argument (the git subcommand)
        subcommand = None
        for arg in arguments:
            if not arg.startswith("-"):
                subcommand = arg.lower()
                break

        if not subcommand or subcommand not in GIT_ALLOWED_SUBCOMMANDS:
            raise ValueError(
                f"Git subcommand '{subcommand}' is not permitted by Orion security policy. "
                f"Permitted subcommands: {sorted(GIT_ALLOWED_SUBCOMMANDS)}"
            )

    elif cmd_normalized in ("python", "python3"):
        if not arguments:
            raise ValueError("Python command requires arguments.")

        # Reject -c, -i, etc.
        for arg in arguments:
            if arg == "-c" or arg.startswith("-c"):
                raise ValueError("Arbitrary Python code execution (-c) is strictly prohibited.")

        # Allow: --version, -V
        if arguments in (["--version"], ["-V"]):
            return

        # Allow: -m unittest [...], -m pytest [...]
        if len(arguments) >= 2 and arguments[0] == "-m" and arguments[1] in ("unittest", "pytest"):
            return

        raise ValueError(
            f"Python arguments {arguments} are not permitted by Orion security policy. "
            "Only '--version', '-m unittest', and '-m pytest' are currently permitted."
        )


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Execute an allowlisted command in the Orion workspace (requires confirmation). "
        "Permitted commands include read-only git operations and python test commands. "
        "NOTE: This tool uses process-level isolation only (sanitised environment + "
        "dedicated working directory). It does NOT provide OS-level sandboxing."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    async def execute(
        self,
        command: str,
        arguments: list[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Reject attempts to specify custom cwd
        if "cwd" in kwargs:
            raise ValueError(
                "Specifying a custom working directory is not permitted. "
                "Commands always execute in the Orion workspace root."
            )

        # In production / public-demo mode, process-level isolation is not sufficient
        # on shared/unisolated host environments (such as Render Free without VM/container sandbox).
        # Fail closed for public-demo / production environments.
        try:
            from ..config import get_settings
            settings = get_settings()
            if settings.environment.lower() in ("production", "prod", "public-demo", "demo"):
                raise PermissionError(
                    "Command execution is disabled in public-demo / production mode. "
                    "Process-level isolation does not provide an OS-level sandbox. "
                    "Command execution must be moved to a dedicated sandbox runner."
                )
        except PermissionError:
            raise
        except Exception:
            pass

        args = arguments if arguments is not None else []

        # Validate against strict command policy
        validate_command_policy(command, args)

        # Enforce timeout bounds
        effective_timeout = min(max(1.0, float(timeout)), MAX_TIMEOUT)

        # Use the dedicated workspace (not the source tree) as cwd.
        workspace_cwd = str(_get_workspace_root())

        try:
            proc = subprocess.run(
                [command, *args],
                cwd=workspace_cwd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                env=_get_safe_env(),
                check=False,
            )
            return {
                "command": command,
                "arguments": args,
                "return_code": proc.returncode,
                "stdout": _truncate_and_scrub(proc.stdout),
                "stderr": _truncate_and_scrub(proc.stderr),
                "status": "completed",
            }

        except subprocess.TimeoutExpired as exc:
            return {
                "command": command,
                "arguments": args,
                "return_code": -1,
                "stdout": _truncate_and_scrub(exc.stdout or ""),
                "stderr": f"Command timed out after {effective_timeout} seconds.",
                "status": "timeout",
            }
