import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUDIT_DIR = PROJECT_ROOT / "data"
AUDIT_FILE = AUDIT_DIR / "audit.log"


def _scrub_secrets(text: str) -> str:
    """Scrub known API keys and tokens from strings in audit log."""
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


def _sanitize_payload(data: Any) -> Any:
    """
    Sanitize arguments and results to guarantee that file contents
    and secrets are never recorded in the audit log.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            k_upper = str(k).upper()
            if any(term in k_upper for term in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")):
                sanitized[k] = "<REDACTED>"
            elif k == "content":
                sanitized[k] = "<content omitted>"
            else:
                sanitized[k] = _sanitize_payload(v)
        return sanitized
    elif isinstance(data, list):
        return [_sanitize_payload(item) for item in data]
    elif isinstance(data, str):
        return _scrub_secrets(data)
    return data


def log_event(
    event: str,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    status: str = "success",
) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    safe_arguments = _sanitize_payload(arguments or {})
    safe_result = _sanitize_payload(result)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "tool": tool,
        "arguments": safe_arguments,
        "result": safe_result,
        "status": status,
    }

    with AUDIT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False) + "\n")
