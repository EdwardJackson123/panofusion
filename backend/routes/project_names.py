from pathlib import Path

from fastapi import HTTPException


def safe_project_name(name: str) -> str:
    value = (name or "").strip()
    if (
        not value
        or value in {".", ".."}
        or any(ch in value for ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"))
    ):
        raise HTTPException(400, "Invalid project name")
    return value


def project_dir(projects_dir: Path, name: str) -> Path:
    root = projects_dir.resolve()
    candidate = (root / safe_project_name(name)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(400, "Invalid project name")
    return candidate
