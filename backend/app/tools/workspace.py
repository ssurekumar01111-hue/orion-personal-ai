from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.resolve()


def safe_path(relative_path: str = ".") -> Path:
    candidate = (WORKSPACE_ROOT / relative_path).resolve()

    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise PermissionError(
            "Path is outside the Orion workspace."
        ) from exc

    return candidate


def is_protected_file(path: Path) -> bool:
    """
    Check whether a path refers to a sensitive configuration, secret,
    or environment file that must not be read or written by AI tools.
    """
    name = path.name.lower()

    # Exact or prefixed .env patterns (.env, .env.local, .env.prod, etc.)
    if name == ".env" or name.startswith(".env.") or name.startswith(".env"):
        return True

    # Common credential and secret file patterns
    if name in {
        "credentials",
        "credentials.json",
        "secrets.json",
        "token",
        "tokens.json",
        "id_rsa",
        "id_ed25519",
        "id_dsa",
        "id_ecdsa",
        "authorized_keys",
        "known_hosts",
    }:
        return True

    # Secret and private key extensions
    if path.suffix.lower() in {".key", ".pem", ".pfx", ".p12", ".pkcs12"}:
        return True

    return False
