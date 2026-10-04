import subprocess
from typing import Any

from .base import Tool
from .permissions import Permission
from .workspace import WORKSPACE_ROOT


class GitStatusTool(Tool):
    name = "git_status"
    description = (
        "Report the Git repository status of the Orion workspace."
    )
    permission = Permission.AUTOMATIC

    async def execute(self) -> dict[str, Any]:
        """
        Run git status safely via subprocess without shell=True,
        restricted to the Orion workspace directory.
        """
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain=v1", "-b"],
                cwd=str(WORKSPACE_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return {
                "is_repo": False,
                "error": "Git binary not found on host system.",
            }
        except Exception as exc:
            return {
                "is_repo": False,
                "error": str(exc),
            }

        if proc.returncode != 0:
            return {
                "is_repo": False,
                "error": proc.stderr.strip() or "Not a git repository.",
            }

        lines = proc.stdout.splitlines()
        branch = "unknown"
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []

        if lines:
            header = lines[0]
            if header.startswith("## "):
                branch_info = header[3:].strip()
                if " on " in branch_info:
                    branch = branch_info.split(" on ")[-1].strip()
                elif "..." in branch_info:
                    branch = branch_info.split("...")[0].strip()
                else:
                    branch = branch_info

            for line in lines[1:]:
                if len(line) >= 3:
                    x, y = line[0], line[1]
                    item_path = line[3:].strip()
                    if x == "?" and y == "?":
                        untracked.append(item_path)
                    else:
                        if x not in (" ", "?"):
                            staged.append(item_path)
                        if y not in (" ", "?"):
                            unstaged.append(item_path)

        clean = len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0

        return {
            "is_repo": True,
            "branch": branch,
            "clean": clean,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "raw": proc.stdout.strip(),
        }
