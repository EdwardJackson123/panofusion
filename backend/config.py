"""
PanoFusion COLMAP Edition — Configuration
"""
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

# COLMAP executable
COLMAP_EXE = os.environ.get("PANOFUSION_COLMAP", None)

def find_colmap_exe() -> str:
    if COLMAP_EXE and Path(COLMAP_EXE).exists():
        return COLMAP_EXE
    # Bundled: dev mode (in-project) vs packaged mode (extraResources)
    candidates = [
        BASE_DIR.parent / "colmap" / "bin" / "colmap.exe",           # both dev and packaged
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    # PATH
    found = shutil.which("colmap")
    if found:
        return found
    return "colmap"
