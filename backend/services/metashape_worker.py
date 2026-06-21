"""
Metashape Worker Script — runs INSIDE metashape.exe via `metashape.exe -r`
Uses the proven original xPano scripts for alignment + COLMAP export.
Progress reported via stdout PROGRESS:<n>

Usage:
  metashape.exe -r metashape_worker.py --manifest <path> --project <path> --export-dir <path>
"""
import argparse
import json
import math
import os
import sys
import traceback
from pathlib import Path

import Metashape

# Use PanoFusion's own exporter scripts (same directory, ported from verified xPano pipeline)
import align_ground_plane
import export_colmap


def emit_progress(value: int):
    print(f"PROGRESS:{value}", flush=True)


def emit_log(level: str, msg: str):
    print(f"LOG:{level}:{msg}", flush=True)


def load_manifest(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--export-dir", required=True)
    p.add_argument("--accuracy", default="high")
    p.add_argument("--keypoint-limit", type=int, default=40000)
    p.add_argument("--tiepoint-limit", type=int, default=0)
    p.add_argument("--no-ground-plane", action="store_true")
    p.add_argument("--up-axis", default="+Y")
    return p.parse_args()


def export_dir_from_argv():
    if "--export-dir" in sys.argv:
        idx = sys.argv.index("--export-dir")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1])
    return None


def write_crash_report():
    export_dir = export_dir_from_argv()
    if not export_dir:
        return
    try:
        report_path = export_dir / "workspace" / "metashape_worker_error.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass


def gpu_device_name(device):
    if isinstance(device, dict):
        return " ".join(str(v) for v in device.values())
    return str(device)


def configure_gpu_devices():
    """Avoid using integrated GPUs by default; Intel OpenCL often crashes during matching."""
    mode = os.environ.get("PANOFUSION_GPU_MODE", "auto").strip().lower()
    try:
        devices = list(Metashape.app.enumGPUDevices())
    except Exception as exc:
        emit_log("warn", f"GPU device query failed, using Metashape defaults: {exc}")
        return

    if not devices:
        emit_log("warn", "No GPU devices reported by Metashape; using CPU")
        try:
            Metashape.app.gpu_mask = 0
            Metashape.app.cpu_enable = True
        except Exception:
            pass
        return

    if mode in {"cpu", "off", "none"}:
        try:
            Metashape.app.gpu_mask = 0
            Metashape.app.cpu_enable = True
        except Exception:
            pass
        emit_log("info", "GPU disabled by PANOFUSION_GPU_MODE=cpu")
        return

    names = [gpu_device_name(d) for d in devices]
    lower_names = [n.lower() for n in names]
    has_discrete = any(("nvidia" in n or "amd" in n or "radeon" in n) for n in lower_names)
    mask = 0
    selected = []
    for index, name in enumerate(names):
        lname = name.lower()
        if mode == "all":
            include = True
        elif mode == "nvidia":
            include = "nvidia" in lname
        elif mode in {"amd", "radeon"}:
            include = "amd" in lname or "radeon" in lname
        else:
            include = not ("intel" in lname and has_discrete)

        if include:
            mask |= (1 << index)
            selected.append(name)

    if mask == 0:
        emit_log("warn", f"No GPU selected for mode '{mode}', falling back to CPU")
        try:
            Metashape.app.gpu_mask = 0
            Metashape.app.cpu_enable = True
        except Exception:
            pass
        return

    try:
        Metashape.app.gpu_mask = mask
        Metashape.app.cpu_enable = True
    except Exception as exc:
        emit_log("warn", f"Failed to set GPU mask, using Metashape defaults: {exc}")
        return

    emit_log("info", "GPU devices selected: " + "; ".join(selected))
    skipped = [name for name in names if name not in selected]
    if skipped:
        emit_log("info", "GPU devices skipped: " + "; ".join(skipped))


# ═══════════════════════════════════════════════
# Sensor setup (same as xPano metashape_pipeline.py)
# ═══════════════════════════════════════════════

def copy_sensor_geometry(dst, src):
    if not src:
        return
    if src.width and src.height:
        dst.width = src.width
        dst.height = src.height
    # Only copy pixel/focal if the source has valid values
    if src.pixel_width and src.pixel_height and src.pixel_width > 0:
        dst.pixel_width = src.pixel_width
        dst.pixel_height = src.pixel_height
    if src.focal_length and src.focal_length > 0:
        dst.focal_length = src.focal_length
    try:
        if src.calibration:
            dst.calibration = src.calibration
    except Exception:
        pass


def configure_fisheye_sensor(sensor):
    sensor.type = Metashape.Sensor.Type.EquidistantFisheye
    sensor.pixel_width = 0.0024
    sensor.pixel_height = 0.0024
    sensor.focal_length = 2.5
    sensor.fixed_params = ["B1", "B2", "K4"]
    calib = sensor.calibration
    if calib:
        calib.b1 = 0
        calib.b2 = 0
        calib.k4 = 0
        calib.type = Metashape.Sensor.Type.EquidistantFisheye


def make_track_sensor(chunk, source_camera, label, sensor_type):
    sensor = chunk.addSensor()
    sensor.label = label
    copy_sensor_geometry(sensor, source_camera.sensor if source_camera else None)
    sensor.type = sensor_type
    if sensor_type == Metashape.Sensor.Type.EquidistantFisheye:
        configure_fisheye_sensor(sensor)
    elif sensor_type == Metashape.Sensor.Type.Frame:
        calib = sensor.calibration
        if calib:
            calib.type = Metashape.Sensor.Type.Frame
    return sensor


def camera_path_name(camera):
    try:
        return Path(camera.photo.path).name.lower()
    except Exception:
        return camera.label.lower()


# ═══════════════════════════════════════════════
# Import tracks (same as xPano metashape_pipeline.py)
# ═══════════════════════════════════════════════

def add_photos_get_new(chunk, paths, group_key=None):
    before = len(chunk.cameras)
    kwargs = {"load_xmp_accuracy": True}
    if group_key is not None:
        kwargs["group"] = group_key
    chunk.addPhotos([str(p) for p in paths], **kwargs)
    return list(chunk.cameras)[before:]


def import_panorama_track(chunk, track):
    station_groups = []
    left_sensor = None
    right_sensor = None
    left_label = track.get("left_sensor_label", f"{track['track_id']}_left")
    right_label = track.get("right_sensor_label", f"{track['track_id']}_right")

    for frame in track.get("frames", []):
        group = chunk.addCameraGroup()
        group.label = frame.get("group_label", frame.get("frame_id", track["track_id"]))
        group.type = Metashape.CameraGroup.Type.Folder
        station_groups.append(group)

        paths = [frame["left"], frame["right"]]
        new_cameras = add_photos_get_new(chunk, paths, group_key=group.key)
        for camera in new_cameras:
            name = camera_path_name(camera)
            if name == Path(frame["left"]).name.lower() or name.endswith("_left.jpg"):
                if left_sensor is None:
                    left_sensor = make_track_sensor(chunk, camera, left_label, Metashape.Sensor.Type.EquidistantFisheye)
                camera.sensor = left_sensor
            elif name == Path(frame["right"]).name.lower() or name.endswith("_right.jpg"):
                if right_sensor is None:
                    right_sensor = make_track_sensor(chunk, camera, right_label, Metashape.Sensor.Type.EquidistantFisheye)
                camera.sensor = right_sensor

    return station_groups


def import_photo_track(chunk, track):
    group = chunk.addCameraGroup()
    group.label = track.get("group_label", f"{track['track_id']}_photos")
    group.type = Metashape.CameraGroup.Type.Folder

    photo_sensors = track.get("photo_sensors") or []
    if photo_sensors:
        imported = []
        for sensor_group in photo_sensors:
            photos = sensor_group.get("photos", [])
            if not photos:
                continue
            ident = sensor_group.get("camera_identity", {})
            if not ident.get("make") and not ident.get("focal_length"):
                emit_log("warn", f"照片组 {sensor_group.get('sensor_label')} 缺少 EXIF 数据，标定可能不准确")
            new_cameras = add_photos_get_new(chunk, photos, group_key=group.key)
            if not new_cameras:
                continue
            sensor = make_track_sensor(
                chunk, new_cameras[0],
                sensor_group.get("sensor_label", track.get("sensor_label", f"{track['track_id']}_frame")),
                Metashape.Sensor.Type.Frame,
            )
            for camera in new_cameras:
                camera.sensor = sensor
            imported.extend(new_cameras)
        return imported

    photos = track.get("photos", [])
    if not photos:
        return []
    new_cameras = add_photos_get_new(chunk, photos, group_key=group.key)
    sensors_by_size = {}
    base_label = track.get("sensor_label", f"{track['track_id']}_frame")
    for camera in new_cameras:
        src = camera.sensor
        key = (getattr(src, "width", 0), getattr(src, "height", 0))
        if key not in sensors_by_size:
            suffix = "" if not sensors_by_size else f"_{len(sensors_by_size) + 1:02d}"
            sensor = make_track_sensor(chunk, camera, f"{base_label}{suffix}", Metashape.Sensor.Type.Frame)
            sensors_by_size[key] = sensor
        camera.sensor = sensors_by_size[key]
    return new_cameras


def import_manifest_tracks(chunk, manifest):
    station_groups = []
    for track in manifest.get("tracks", []):
        track_type = track.get("track_type")
        if track_type == "panorama_video":
            station_groups.extend(import_panorama_track(chunk, track))
        elif track_type in {"standard_photos", "aerial_photos"}:
            import_photo_track(chunk, track)
        else:
            emit_log("warn", f"Unknown track_type: {track_type}")

    # Prune unused sensors
    used = set()
    for c in chunk.cameras:
        if c.sensor:
            used.add(c.sensor.key)
    for s in list(chunk.sensors):
        if s.key not in used:
            try:
                chunk.remove(s)
            except Exception:
                pass
    return station_groups


def used_sensors(chunk):
    sensors = []
    seen = set()
    for camera in chunk.cameras:
        if camera.sensor and camera.sensor.key not in seen:
            sensors.append(camera.sensor)
            seen.add(camera.sensor.key)
    return sensors


def station_distances(chunk):
    distances = []
    for group in chunk.camera_groups:
        cameras = [c for c in chunk.cameras if c.group == group and c.transform]
        if len(cameras) != 2:
            continue
        centers = [chunk.transform.matrix.mulp(c.center) for c in cameras]
        delta = centers[0] - centers[1]
        distances.append(math.sqrt(delta.x * delta.x + delta.y * delta.y + delta.z * delta.z))
    return distances


def identity4():
    return Metashape.Matrix.Diag([1, 1, 1, 1])


def rot_x(angle):
    c = math.cos(angle)
    s = math.sin(angle)
    return Metashape.Matrix([
        [1, 0, 0, 0],
        [0, c, -s, 0],
        [0, s, c, 0],
        [0, 0, 0, 1],
    ])


def rot_z(angle):
    c = math.cos(angle)
    s = math.sin(angle)
    return Metashape.Matrix([
        [c, -s, 0, 0],
        [s, c, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ])


def write_alignment_summary(chunk, export_dir, project_path):
    aligned = [c for c in chunk.cameras if c.transform]
    distances = station_distances(chunk)
    lines = [
        "PanoFusion Alignment Summary",
        f"project={project_path}",
        f"cameras={len(chunk.cameras)}",
        f"aligned={len(aligned)}",
        f"groups={len(chunk.camera_groups)}",
        f"sensors={len(used_sensors(chunk))}",
    ]
    if distances:
        lines.append(
            "station_baseline_min_max_avg="
            f"{min(distances):.9f},{max(distances):.9f},{(sum(distances) / len(distances)):.9f}"
        )
    for sensor in used_sensors(chunk):
        calib = sensor.calibration
        lines.append(
            "sensor="
            f"{sensor.label},type={sensor.type},size={sensor.width}x{sensor.height},"
            f"pixel={sensor.pixel_width},{sensor.pixel_height},focal={sensor.focal_length},"
            f"calib_f={getattr(calib, 'f', None)},fixed={list(sensor.fixed_params)}"
        )
    Path(project_path).parent.joinpath("alignment_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ═══════════════════════════════════════════════
# Main — exactly matching xPano's metashape_pipeline.py
# ═══════════════════════════════════════════════

def main():
    args = parse_args()
    project_path = Path(args.project)
    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    doc = Metashape.app.document
    chunk = doc.addChunk()
    doc.chunk = chunk

    # Map accuracy to downscale
    accuracy_map = {"high": 1, "medium": 2, "low": 4}
    downscale = accuracy_map.get(args.accuracy, 1)

    emit_progress(40)
    manifest = load_manifest(args.manifest)
    station_groups = import_manifest_tracks(chunk, manifest)

    if not chunk.cameras:
        emit_log("error", "No cameras imported")
        sys.exit(1)

    emit_log("info", f"Imported {len(chunk.cameras)} cameras in {len(station_groups)} groups")
    configure_gpu_devices()

    # Set Station type
    for group in station_groups:
        try:
            group.type = Metashape.CameraGroup.Type.Station
        except Exception:
            pass

    emit_progress(55)
    # Match Photos (same params as xPano)
    emit_progress(60)
    emit_log("info", "Matching photos...")
    chunk.matchPhotos(
        downscale=downscale,
        generic_preselection=True,
        reference_preselection=False,
        filter_stationary_points=False,
        guided_matching=False,
        keypoint_limit=args.keypoint_limit,
        tiepoint_limit=args.tiepoint_limit,
    )

    emit_progress(75)
    emit_log("info", "Aligning cameras (adaptive_fitting=True)...")
    chunk.alignCameras(adaptive_fitting=True)
    aligned = sum(1 for c in chunk.cameras if c.transform)
    emit_log("info", f"Aligned: {aligned}/{len(chunk.cameras)}")
    if aligned < 2:
        emit_log("error", f"Not enough aligned cameras: {aligned}/{len(chunk.cameras)}")
        sys.exit(2)
    if aligned < max(2, int(len(chunk.cameras) * 0.2)):
        emit_log("warn", f"Low alignment ratio: {aligned}/{len(chunk.cameras)}")

    # Write alignment summary BEFORE releasing stations (accurate baseline)
    emit_progress(82)
    write_alignment_summary(chunk, export_dir, project_path)
    emit_log("info", "Alignment summary written")

    # Release stations → folders, optimize
    emit_progress(86)
    for group in station_groups:
        try:
            group.type = Metashape.CameraGroup.Type.Folder
        except Exception:
            pass
    chunk.optimizeCameras(fit_b1=False, fit_b2=False, fit_k4=False)

    # Apply up-axis transformation with explicit 4x4 matrices for Metashape API compatibility.
    # align_ground_plane.main() already converts Z-Up→Y-Up via EXPORT_FOR_3DGS.
    # Only apply extra rotation for non-default axes.
    # rot_x(-pi/2): (x,y,z)→(x, z, -y); rot_x(pi/2): (x,y,z)→(x, -z, y)
    axis_map = {
        "+Y": identity4(),
        "-Y": rot_x(math.pi),
        "+Z": rot_x(math.pi / 2),
        "-Z": rot_x(-math.pi / 2),
        "+X": rot_z(-math.pi / 2),
        "-X": rot_z(math.pi / 2),
    }
    if args.up_axis != "+Y":
        chunk.transform.matrix = axis_map.get(args.up_axis, identity4()) * chunk.transform.matrix
        emit_log("info", f"Up axis set to {args.up_axis}")

    # Ground plane alignment
    if not args.no_ground_plane:
        emit_progress(96)
        emit_log("info", "Aligning ground plane...")
        try:
            align_ground_plane.main()
        except Exception as exc:
            emit_log("warn", f"Ground plane alignment failed, continuing: {exc}")
    else:
        emit_progress(96)
        emit_log("info", "Ground plane alignment skipped")

    emit_progress(97)
    # COLMAP export — use the ORIGINAL xPano export_colmap
    emit_log("info", "Exporting COLMAP / Cubemap (original xPano pipeline)...")
    export_colmap.run_mixed_export(str(export_dir))

    emit_progress(100)
    emit_log("info", "Pipeline complete")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:
        emit_log("error", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        write_crash_report()
        sys.exit(1)
