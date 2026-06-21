"""
Pipeline Orchestrator
1. Build manifest / extract frames
2. Spawn Metashape worker via subprocess
3. Collect progress — directly mapped from worker milestones (no fake interpolation)
"""
import re
import os
import shutil
import subprocess
import time
from pathlib import Path

from config import find_metashape_exe
from .manifest import build_manifest


def _terminate_process_tree(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _is_lock_error(exc: Exception) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 32


def _terminate_stale_processes_for_output(output_dir: Path, add_log):
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        return

    script = r"""
$needle = $env:PANOFUSION_OUTPUT_DIR
if ([string]::IsNullOrWhiteSpace($needle)) { exit 0 }
$needle = $needle.ToLowerInvariant().Replace('/', '\')
Get-CimInstance Win32_Process |
  Where-Object {
    ($_.Name -eq 'metashape.exe' -or $_.Name -eq 'ffmpeg.exe' -or $_.Name -eq 'ffprobe.exe') -and
    $_.CommandLine -and
    $_.CommandLine.ToLowerInvariant().Replace('/', '\').Contains($needle)
  } |
  ForEach-Object { $_.ProcessId }
"""
    env = os.environ.copy()
    env["PANOFUSION_OUTPUT_DIR"] = str(output_dir)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        add_log("warn", f"检查遗留进程失败: {exc}")
        return

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        add_log("warn", f"检查遗留进程失败: {detail[:160]}")
        return

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        add_log("warn", f"终止遗留进程: PID {line}")
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", line],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def _remove_tree_with_retry(path: Path, output_dir: Path, add_log):
    for attempt in range(3):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            if not _is_lock_error(exc) or attempt == 2:
                raise
            add_log("warn", f"{path.name} 被占用，正在清理遗留进程后重试...")
            _terminate_stale_processes_for_output(output_dir, add_log)
            time.sleep(0.5)


def run_pipeline(config: dict, update_progress, add_log, is_stopped=None,
                 register_process=None, unregister_process=None):
    output_dir = Path(config["outputDir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    if is_stopped is None:
        is_stopped = lambda: False
    if register_process is None:
        register_process = lambda proc: None
    if unregister_process is None:
        unregister_process = lambda proc: None

    _terminate_stale_processes_for_output(output_dir, add_log)
    for dirname in ("workspace", "images", "sparse"):
        path = output_dir / dirname
        if path.exists():
            add_log("info", f"清理旧输出: {dirname}")
            _remove_tree_with_retry(path, output_dir, add_log)

    work_dir = output_dir / "workspace"
    work_dir.mkdir(parents=True, exist_ok=True)

    seconds_per_frame = config.get("secondsPerFrame", 1.0)
    max_frames = config.get("maxFrames", 0) or 0
    accuracy = config.get("accuracy", "high")
    keypoint_limit = config.get("keypointLimit", 40000)
    tiepoint_limit = config.get("tiepointLimit", 0)
    ground_plane = config.get("groundPlane", True)
    up_axis = config.get("upAxis", "+Y")
    tracks_config = config.get("tracks", [])

    # ═══ Phase 1: Extract (0–30%) ═══
    panorama_videos, standard_photo_tracks, aerial_photo_tracks = [], [], []
    for track in tracks_config:
        tt = track.get("trackType")
        if tt == "panorama_video": panorama_videos.extend(track.get("paths", []))
        elif tt == "standard_photos": standard_photo_tracks.append((track.get("label", ""), track.get("paths", [])))
        elif tt == "aerial_photos": aerial_photo_tracks.append((track.get("label", ""), track.get("paths", [])))

    def extract_progress(cur, total):
        # Extraction ring fills proportionally to actual frame processing
        t = max(total, 1)
        extract_ring = int(100 * cur / t)
        overall = int(25 * cur / t)
        update_progress("extracting", overall, f"抽帧 {cur}/{total}", extract_ring, 0, 0)

    manifest, manifest_path = build_manifest(
        output_dir=output_dir, panorama_videos=panorama_videos,
        standard_photo_tracks=standard_photo_tracks, aerial_photo_tracks=aerial_photo_tracks,
        seconds_per_frame=seconds_per_frame, max_frames=max_frames,
        progress_cb=extract_progress, log_cb=lambda msg: add_log("info", msg),
        is_stopped=is_stopped, register_process=register_process,
        unregister_process=unregister_process,
    )

    total_frames = sum(len(t.get("frames", [])) for t in manifest.get("tracks", []) if t.get("track_type") == "panorama_video")
    total_photos = sum(len(t.get("photos", [])) for t in manifest.get("tracks", []) if t.get("track_type") != "panorama_video")
    add_log("info", f"全景帧: {total_frames}, 补拍照片: {total_photos}")
    # Only advance overall, don't force extract ring to 100 — it already reached 100 via extract_progress
    update_progress("aligning", 25, f"素材就绪 ({total_frames} 帧)", 100, 2, 0)

    if is_stopped():
        update_progress("idle", 0, "已停止", 0, 0, 0); return

    # ═══ Phase 2: Metashape (30–96%) ═══
    metashape_exe = find_metashape_exe()
    add_log("info", f"Metashape: {metashape_exe}")
    worker_script = Path(__file__).resolve().parent / "metashape_worker.py"
    worker_log_path = work_dir / "metashape_worker.log"

    cmd = [metashape_exe, "-r", str(worker_script),
           "--manifest", str(manifest_path),
           "--project", str(work_dir / "panofusion.psx"),
           "--export-dir", str(output_dir),
           "--accuracy", accuracy,
           "--keypoint-limit", str(keypoint_limit),
           "--tiepoint-limit", str(tiepoint_limit),
           "--up-axis", up_axis]
    if not ground_plane:
        cmd.append("--no-ground-plane")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    register_process(proc)
    recent_output = []
    last_worker_error = None
    worker_log = worker_log_path.open("w", encoding="utf-8", errors="replace")

    try:
        # Threaded reader so stop flag is checked even when subprocess is silent
        import threading, queue
        q: queue.Queue = queue.Queue()
        def reader():
            try:
                for line in proc.stdout:
                    q.put(line)
            except Exception:
                pass
            q.put(None)
        t = threading.Thread(target=reader, daemon=True)
        t.start()

        while True:
            try:
                line = q.get(timeout=0.5)
            except queue.Empty:
                if is_stopped():
                    add_log("warn", "正在终止...")
                    _terminate_process_tree(proc)
                    update_progress("idle", 0, "已停止", 0, 0, 0); return
                continue
            if line is None:
                break

            line = line.rstrip()
            if not line: continue
            try:
                worker_log.write(line + "\n")
                worker_log.flush()
            except Exception:
                pass
            recent_output.append(line)
            if len(recent_output) > 20:
                recent_output = recent_output[-20:]

            if line.startswith("PROGRESS:"):
                try:
                    raw = int(line.split(":", 1)[1].strip())
                    # Spread across 25-85%
                    phase_map = {40:28, 55:35, 60:48, 75:62, 82:72, 90:80, 96:84, 97:85}
                    overall = 30
                    for k in sorted(phase_map):
                        if raw >= k: overall = phase_map[k]
                    align_ring = int((overall - 25) / 60 * 100) if overall > 25 else 0
                    update_progress("aligning", overall, _phase_label(raw), 100, min(100, align_ring), 0)
                except Exception: pass

            elif line.startswith("LOG:"):
                try:
                    parts = line.split(":", 2)
                    add_log(parts[1], parts[2])
                    if parts[1] == "error":
                        last_worker_error = parts[2]
                    if "Exporting COLMAP" in parts[2]:
                        update_progress("exporting", 85, "导出 COLMAP...", 100, 100, 2)
                except Exception: pass

            elif "处理中" in line:
                m = re.search(r"\[(\d+)/(\d+)\]", line)
                if m:
                    cur, total = int(m.group(1)), int(m.group(2))
                    pct = 85 + int(14 * cur / max(total, 1))
                    export_ring = int(97 * cur / max(total, 1)) + 2
                    update_progress("exporting", min(pct, 99), f"导出 {cur}/{total}", 100, 100, min(99, export_ring))

            elif line.strip():
                add_log("info", line)

        t.join(timeout=2)
        if is_stopped():
            update_progress("idle", 0, "已停止", 0, 0, 0); return
        rc = proc.wait()
        if rc != 0:
            add_log("error", f"Metashape 退出码: {rc}")
            detail = last_worker_error or next((x for x in reversed(recent_output) if x.strip()), "")
            if detail:
                add_log("error", f"Metashape 失败详情: {detail[:500]}")
                raise RuntimeError(f"Metashape failed (exit {rc}): {detail[:500]}")
            raise RuntimeError(f"Metashape failed (exit {rc})")
    finally:
        try:
            worker_log.close()
        except Exception:
            pass
        unregister_process(proc)

    # Clean up internal manifest
    try:
        manifest_path.unlink()
    except Exception:
        pass

    update_progress("done", 100, "处理完成", 100, 100, 100)
    add_log("info", "管线完成")


def _phase_label(raw: int) -> str:
    if raw < 40: return "初始化..."
    if raw < 55: return "导入素材..."
    if raw < 60: return "特征匹配中..."
    if raw < 75: return "相机对齐中..."
    if raw < 82: return "优化参数..."
    if raw < 90: return "保存工程..."
    if raw < 97: return "地平面校正..."
    return "准备导出..."
