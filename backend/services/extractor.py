"""
Frame extraction service — ported from xpano_extract.py
Extracts dual-fisheye frames from .osv/.insv panoramic videos using ffmpeg.
"""
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

SUPPORTED_EXTENSIONS = {".insv", ".osv", ".mp4"}

# -- locate bundled ffmpeg / ffprobe ---------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                    # project root (dev) or resources/ (packaged)


def _find_ffmpeg(tool="ffmpeg"):
    """Resolve ffmpeg/ffprobe path: bundled copy first, then system PATH."""
    exe_name = f"{tool}.exe" if os.name == "nt" else tool
    # 1) Bundled at backend/../ffmpeg.exe (dev) or resources/ffmpeg.exe (packaged)
    bundled = _PROJECT_ROOT / exe_name
    if bundled.exists():
        return str(bundled)
    # 2) Bundled alongside the backend (resources/backend/)
    sibling = _BACKEND_DIR / exe_name
    if sibling.exists():
        return str(sibling)
    # 3) System PATH
    found = shutil.which(tool)
    if found:
        return found
    # 4) Fallback — let subprocess report FileNotFoundError
    return tool


def _ffmpeg_bin():
    return _find_ffmpeg("ffmpeg")


def _ffprobe_bin():
    return _find_ffmpeg("ffprobe")


class ExtractionStopped(Exception):
    pass


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


def _apply_exif(img_path: Path, model: str, make: str):
    try:
        import piexif
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        exif_dict["0th"][piexif.ImageIFD.Make] = make.encode()
        exif_dict["0th"][piexif.ImageIFD.Model] = model.encode()
        piexif.insert(piexif.dump(exif_dict), str(img_path))
    except Exception:
        pass


def _probe_duration_seconds(input_path: Path, log_cb=None):
    try:
        result = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None
    except Exception as exc:
        if log_cb:
            log_cb(f"ffprobe duration unavailable for {input_path.name}: {exc}")
        return None


def _expected_frame_count(input_path: Path, fps, max_frames, log_cb=None):
    if max_frames and max_frames > 0:
        return max_frames
    duration = _probe_duration_seconds(input_path, log_cb=log_cb)
    if not duration:
        return None
    return max(1, int(duration * fps + 0.999999))


def _count_generated_pairs(out_root: Path, base_name: str):
    if not out_root or not base_name:
        return 0
    left_count = len(list(out_root.glob(f"{base_name}_L_*.jpg")))
    right_count = len(list(out_root.glob(f"{base_name}_R_*.jpg")))
    return min(left_count, right_count)


def _run_ffmpeg(cmd, input_path: Path, fps, max_frames, progress_cb=None, log_cb=None,
                out_root=None, base_name=None, is_stopped=None,
                register_process=None, unregister_process=None):
    expected_frames = _expected_frame_count(input_path, fps, max_frames, log_cb=log_cb)
    if log_cb:
        if expected_frames:
            log_cb(f"ffmpeg extracting {input_path.name}, expected frames: {expected_frames}")
        else:
            log_cb(f"ffmpeg extracting {input_path.name}, expected frames unknown")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=creationflags,
    )
    if register_process:
        register_process(proc)

    last_frame = 0
    last_logged_frame = 0
    last_log_time = 0.0
    frame_lock = threading.Lock()
    stderr_lines = []  # collect stderr for diagnostics

    def emit_progress(current, final=False):
        if not progress_cb:
            return
        total = expected_frames or 100
        if final:
            current = total
        elif expected_frames:
            current = max(0, min(int(current), total))
        else:
            current = max(0, min(int(current), total - 1))
        progress_cb(current, total)

    def set_last_frame(value):
        nonlocal last_frame
        with frame_lock:
            last_frame = max(last_frame, int(value))
            return last_frame

    def get_last_frame():
        with frame_lock:
            return last_frame

    def read_stdout():
        try:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                key, sep, value = line.partition("=")
                if sep and key == "frame":
                    try:
                        emit_progress(set_last_frame(int(value.strip())))
                    except ValueError:
                        pass
                elif sep and key == "progress" and value == "end":
                    emit_progress(expected_frames or get_last_frame(), final=True)
        finally:
            pass

    def read_stderr():
        try:
            for raw_line in proc.stderr:
                line = raw_line.strip()
                if line:
                    stderr_lines.append(line)
        finally:
            pass

    stdout_reader = threading.Thread(target=read_stdout, daemon=True)
    stderr_reader = threading.Thread(target=read_stderr, daemon=True)
    stdout_reader.start()
    stderr_reader.start()

    out_root = Path(out_root) if out_root else None
    log_step = max(1, (expected_frames or 100) // 20)

    while proc.poll() is None:
        if is_stopped and is_stopped():
            if log_cb:
                log_cb("ffmpeg stop requested")
            _terminate_process_tree(proc)
            if unregister_process:
                unregister_process(proc)
            raise ExtractionStopped("Extraction stopped")

        generated = _count_generated_pairs(out_root, base_name)
        if generated:
            emit_progress(set_last_frame(generated))

        now = time.monotonic()
        current_frame = get_last_frame()
        if log_cb and expected_frames and (
            current_frame - last_logged_frame >= log_step or now - last_log_time >= 5
        ):
            last_logged_frame = current_frame
            last_log_time = now
            log_cb(f"extract progress {min(current_frame, expected_frames)}/{expected_frames}")
        time.sleep(0.25)

    rc = proc.wait()
    stdout_reader.join(timeout=2)
    stderr_reader.join(timeout=2)
    if unregister_process:
        unregister_process(proc)
    generated = _count_generated_pairs(out_root, base_name)
    if generated:
        emit_progress(set_last_frame(generated))
    if is_stopped and is_stopped():
        raise ExtractionStopped("Extraction stopped")
    if rc != 0:
        stderr_tail = "\n".join(stderr_lines[-30:]) if stderr_lines else "(no stderr output)"
        if log_cb:
            log_cb(f"ffmpeg failed (exit {rc}): {stderr_tail[:500]}")
        raise subprocess.CalledProcessError(rc, cmd, output=stderr_tail[:500])


def _extract_one(task, fps, out_root, max_frames, preview_cb, progress_cb, log_cb,
                 model_prefix, is_stopped=None, register_process=None, unregister_process=None):
    left = task["left_file"]
    right = task["right_file"]
    base_name = task["clean_name"]

    ffmpeg_bin = _ffmpeg_bin()
    if task["type"] == "insta_split":
        cmd = [
            ffmpeg_bin, "-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats",
            "-i", str(left), "-i", str(right),
            "-map", "0:0", "-vf", f"fps={fps}",
        ]
        if max_frames and max_frames > 0:
            cmd.extend(["-frames:v", str(max_frames)])
        cmd.extend([
            "-q:v", "2", str(out_root / f"{base_name}_L_%05d.jpg"),
            "-map", "1:0", "-vf", f"fps={fps}",
        ])
        if max_frames and max_frames > 0:
            cmd.extend(["-frames:v", str(max_frames)])
        cmd.extend(["-q:v", "2", str(out_root / f"{base_name}_R_%05d.jpg")])
    else:
        cmd = [
            ffmpeg_bin, "-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats",
            "-i", str(left),
            "-map", "0:0", "-vf", f"fps={fps}",
        ]
        if max_frames and max_frames > 0:
            cmd.extend(["-frames:v", str(max_frames)])
        cmd.extend([
            "-q:v", "2", str(out_root / f"{base_name}_L_%05d.jpg"),
            "-map", "0:1", "-vf", f"fps={fps}",
        ])
        if max_frames and max_frames > 0:
            cmd.extend(["-frames:v", str(max_frames)])
        cmd.extend(["-q:v", "2", str(out_root / f"{base_name}_R_%05d.jpg")])

    _run_ffmpeg(cmd, left, fps, max_frames, progress_cb=progress_cb, log_cb=log_cb,
                out_root=out_root, base_name=base_name, is_stopped=is_stopped,
                register_process=register_process, unregister_process=unregister_process)

    left_files = sorted(out_root.glob(f"{base_name}_L_*.jpg"))
    right_files = sorted(out_root.glob(f"{base_name}_R_*.jpg"))
    count = min(len(left_files), len(right_files))
    if max_frames and max_frames > 0:
        count = min(count, max_frames)

    extracted = []
    for idx in range(count):
        if is_stopped and is_stopped():
            raise ExtractionStopped("Extraction stopped")
        frame_idx = idx + 1
        frame_dir = out_root / f"{base_name}_frame_{frame_idx:05d}"
        frame_dir.mkdir(exist_ok=True)
        ldst = frame_dir / f"{base_name}_frame_{frame_idx:05d}_left.jpg"
        rdst = frame_dir / f"{base_name}_frame_{frame_idx:05d}_right.jpg"
        shutil.move(str(left_files[idx]), str(ldst))
        shutil.move(str(right_files[idx]), str(rdst))
        make = "Insta360" if left.suffix.lower() == ".insv" else "DJI"
        model_root = model_prefix or make.lower()
        _apply_exif(ldst, f"{model_root}_left", make)
        _apply_exif(rdst, f"{model_root}_right", make)
        extracted.append((ldst, rdst))
        if progress_cb:
            progress_cb(frame_idx, count)

    return extracted


def extract_frames(input_path, out_root, fps, max_frames=0, progress_cb=None, log_cb=None,
                   model_prefix=None, is_stopped=None, register_process=None, unregister_process=None):
    """Extract dual-fisheye frames from a panoramic video."""
    input_path = Path(input_path)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    pair_map = {}
    if input_path.suffix.lower() == ".insv":
        m = re.search(r"(VID_\d+_\d+)_(00|10)_(\d+)", input_path.name)
        if m:
            prefix, side, suffix = m.groups()
            other = "10" if side == "00" else "00"
            partner = input_path.parent / f"{prefix}_{other}_{suffix}.insv"
            if partner.exists():
                pair_map[input_path] = partner

    task = {
        "clean_name": input_path.stem,
        "left_file": input_path,
        "right_file": pair_map.get(input_path, input_path),
        "type": "insta_split" if input_path.suffix.lower() == ".insv" and pair_map.get(input_path) else "dji_dual",
    }

    if progress_cb:
        progress_cb(0, max_frames if max_frames and max_frames > 0 else 1)

    extracted = _extract_one(
        task, fps, out_root, max_frames, None, progress_cb, log_cb, model_prefix,
        is_stopped=is_stopped, register_process=register_process,
        unregister_process=unregister_process,
    )

    if progress_cb:
        progress_cb(1, 1)

    return extracted
