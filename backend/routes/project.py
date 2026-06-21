"""
Project management API routes
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import PROJECTS_DIR
from routes.project_names import project_dir, safe_project_name

router = APIRouter()


class TrackDef(BaseModel):
    trackType: str
    label: str
    paths: list[str]


class CreateProjectRequest(BaseModel):
    name: str
    outputDir: str
    metashapeExe: str = ""
    secondsPerFrame: float = 1.0
    maxFrames: int = 0
    accuracy: str = "high"
    keypointLimit: int = 40000
    tiepointLimit: int = 0
    groundPlane: bool = True
    upAxis: str = "+Y"
    tracks: list[TrackDef] = Field(default_factory=list)


class TrackSummary(BaseModel):
    trackType: str
    label: str
    paths: list[str]


class ProjectSummary(BaseModel):
    name: str
    outputDir: str
    manifestPath: Optional[str] = None
    tracks: list[TrackSummary] = Field(default_factory=list)
    createdAt: str


@router.get("/projects")
async def list_projects():
    """List all saved projects"""
    projects = []
    if PROJECTS_DIR.exists():
        for proj_dir in sorted(PROJECTS_DIR.iterdir(), reverse=True):
            if proj_dir.is_dir():
                config_path = proj_dir / "config.json"
                if config_path.exists():
                    cfg = json.loads(config_path.read_text(encoding="utf-8"))
                    projects.append(ProjectSummary(
                        name=proj_dir.name,
                        outputDir=cfg.get("outputDir", ""),
                        manifestPath=cfg.get("manifestPath"),
                        tracks=cfg.get("tracks", []),
                        createdAt=cfg.get("createdAt", ""),
                    ))
    return {"success": True, "data": [p.model_dump() for p in projects]}


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project with tracks"""
    if not req.name or not req.outputDir:
        raise HTTPException(400, "name and outputDir are required")

    name = safe_project_name(req.name)
    proj_dir = project_dir(PROJECTS_DIR, name)
    proj_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "name": name,
        "outputDir": req.outputDir,
        "metashapeExe": req.metashapeExe,
        "secondsPerFrame": req.secondsPerFrame,
        "maxFrames": req.maxFrames,
        "accuracy": req.accuracy,
        "keypointLimit": req.keypointLimit,
        "tiepointLimit": req.tiepointLimit,
        "groundPlane": req.groundPlane,
        "upAxis": req.upAxis,
        "tracks": [t.model_dump() for t in req.tracks],
        "manifestPath": None,
        "createdAt": datetime.now().isoformat(),
    }

    (proj_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"success": True, "data": ProjectSummary(
        name=name,
        outputDir=req.outputDir,
        tracks=[TrackSummary(**t.model_dump()) for t in req.tracks],
        createdAt=config["createdAt"],
    ).model_dump()}


@router.get("/projects/{name}")
async def get_project(name: str):
    """Get a single project's config"""
    config_path = project_dir(PROJECTS_DIR, name) / "config.json"
    if not config_path.exists():
        raise HTTPException(404, "Project not found")
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    return {"success": True, "data": cfg}
