"""
PanoFusion Configuration
"""
import os
import shutil
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "projects"
WORK_DIR = BASE_DIR / "work"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Pixel size and focal length for dual-fisheye sensors
FISHEYE_PIXEL_SIZE_MM = 0.0024
FISHEYE_FOCAL_LENGTH_MM = 2.5
FIXED_PARAMS = ["B1", "B2", "K4"]


def find_metashape_exe() -> str:
    """
    Auto-detect Metashape executable. Search order:
    1. PANOFUSION_METASHAPE env var
    2. XPANO_METASHAPE env var
    3. Bundled portable: ./Metashape/App/Metashape/metashape.exe (relative to app root)
    4. Common install paths
    5. PATH search
    """
    # Env vars
    for var in ("PANOFUSION_METASHAPE", "XPANO_METASHAPE"):
        val = os.environ.get(var)
        if val and Path(val).exists():
            return val

    app_dir = BASE_DIR.parent
    bundled_candidates = [
        app_dir / "Metashape" / "App" / "Metashape" / "metashape.exe",
        app_dir.parent / "Metashape" / "App" / "Metashape" / "metashape.exe",
    ]
    for bundled in bundled_candidates:
        if bundled.exists():
            return str(bundled)

    # Common paths
    candidates = [
        Path(r"E:\FastProgram\Metashape\metashape.exe"),
        Path(r"C:\Program Files\Agisoft\Metashape Pro\metashape.exe"),
        Path(r"C:\Program Files\Agisoft\Metashape\metashape.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    # PATH
    found = shutil.which("metashape.exe")
    if found:
        return found

    # Fallback
    return "metashape.exe"
