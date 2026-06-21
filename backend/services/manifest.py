"""
Manifest building service — ported from xpano_tracks.py
Builds a JSON manifest describing all material tracks for the pipeline.
"""
import json
import re
from pathlib import Path

from .extractor import extract_frames

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}
PANO_EXTENSIONS = {".osv", ".insv", ".mp4"}


def safe_id(text):
    value = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "track"


def make_track_id(index, label):
    return f"track_{index:03d}_{safe_id(label).lower()}"


def iter_photo_paths(paths):
    result = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            result.extend(p for p in path.rglob("*") if p.suffix.lower() in PHOTO_EXTENSIONS)
        elif path.suffix.lower() in PHOTO_EXTENSIONS:
            result.append(path)
    return sorted(dict.fromkeys(p.resolve() for p in result))


def _decode_exif_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip("\x00 ")
    return str(value).strip()


def _decode_exif_rational(value):
    if value is None:
        return ""
    if isinstance(value, tuple) and len(value) == 2:
        num, den = value
        return f"{num}/{den}" if den else str(num)
    return str(value)


def read_photo_identity(path):
    from PIL import Image
    path = Path(path)
    with Image.open(path) as image:
        width, height = image.size

    identity = {"width": width, "height": height, "make": "", "model": "",
                 "lens_make": "", "lens_model": "", "focal_length": "", "focal_length_35mm": ""}
    try:
        import piexif
        exif = piexif.load(str(path))
    except Exception:
        return identity

    zeroth = exif.get("0th", {})
    exif_ifd = exif.get("Exif", {})
    identity.update({
        "make": _decode_exif_text(zeroth.get(piexif.ImageIFD.Make)),
        "model": _decode_exif_text(zeroth.get(piexif.ImageIFD.Model)),
        "lens_make": _decode_exif_text(exif_ifd.get(piexif.ExifIFD.LensMake)),
        "lens_model": _decode_exif_text(exif_ifd.get(piexif.ExifIFD.LensModel)),
        "focal_length": _decode_exif_rational(exif_ifd.get(piexif.ExifIFD.FocalLength)),
        "focal_length_35mm": _decode_exif_rational(exif_ifd.get(piexif.ExifIFD.FocalLengthIn35mmFilm)),
    })
    return identity


def photo_sensor_key(identity):
    return (identity["width"], identity["height"], identity["make"].casefold(),
            identity["model"].casefold(), identity["lens_make"].casefold(),
            identity["lens_model"].casefold(), identity["focal_length"], identity["focal_length_35mm"])


def build_photo_sensor_groups(base_label, photos):
    groups = {}
    for photo in photos:
        identity = read_photo_identity(photo)
        key = photo_sensor_key(identity)
        if key not in groups:
            suffix = "" if not groups else f"_{len(groups) + 1:02d}"
            groups[key] = {"sensor_id": f"{base_label}{suffix}", "sensor_label": f"{base_label}{suffix}",
                           "camera_identity": identity, "photos": []}
        groups[key]["photos"].append(str(photo))
    return list(groups.values())


def build_panorama_track(index, video_path, work_dir, seconds_per_frame, max_frames,
                         progress_cb=None, log_cb=None, is_stopped=None,
                         register_process=None, unregister_process=None):
    video = Path(video_path).resolve()
    if video.suffix.lower() not in PANO_EXTENSIONS:
        raise ValueError(f"Unsupported panorama video: {video}")
    if not video.exists():
        raise FileNotFoundError(video)

    label = video.stem
    track_id = make_track_id(index, label)
    track_root = Path(work_dir) / "frames" / track_id
    fps = 1.0 / max(seconds_per_frame, 0.01)

    extracted = extract_frames(
        input_path=video, out_root=track_root, fps=fps,
        max_frames=max_frames, progress_cb=progress_cb, log_cb=log_cb,
        model_prefix=track_id, is_stopped=is_stopped,
        register_process=register_process, unregister_process=unregister_process,
    )

    frames = []
    for frame_idx, (left_path, right_path) in enumerate(extracted, 1):
        frames.append({
            "frame_id": f"{track_id}_frame_{frame_idx:05d}",
            "group_label": f"{track_id}_frame_{frame_idx:05d}",
            "left": str(Path(left_path).resolve()),
            "right": str(Path(right_path).resolve()),
        })

    return {
        "track_id": track_id,
        "track_type": "panorama_video",
        "device_label": label,
        "source_paths": [str(video)],
        "seconds_per_frame": seconds_per_frame,
        "max_frames": max_frames,
        
        "export_mode": "cubemap",
        "left_sensor_label": f"{track_id}_left",
        "right_sensor_label": f"{track_id}_right",
        "frames": frames,
    }


def build_photo_track(index, label, paths, track_type):
    if track_type not in {"standard_photos", "aerial_photos"}:
        raise ValueError(f"Unsupported photo track type: {track_type}")
    track_id = make_track_id(index, label)
    photos = iter_photo_paths(paths)
    if not photos:
        raise ValueError(f"No photos found for track {label}")
    sensor_label = f"{track_id}_frame"
    photo_sensors = build_photo_sensor_groups(sensor_label, photos)
    return {
        "track_id": track_id,
        "track_type": track_type,
        "device_label": label,
        "source_paths": [str(Path(p).resolve()) for p in paths],
        
        "export_mode": "undistorted_frame",
        "group_label": f"{track_id}_photos",
        "sensor_label": sensor_label,
        "photo_sensors": photo_sensors,
        "photos": [str(p) for p in photos],
    }


def write_manifest(manifest, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_manifest(output_dir, panorama_videos=None, standard_photo_tracks=None,
                   aerial_photo_tracks=None, seconds_per_frame=1.0, max_frames=0,
                   progress_cb=None, log_cb=None, is_stopped=None,
                   register_process=None, unregister_process=None):
    output_dir = Path(output_dir)
    work_dir = output_dir / "workspace"
    tracks = []
    index = 1

    for video in panorama_videos or []:
        tracks.append(build_panorama_track(
            index=index, video_path=video, work_dir=work_dir,
            seconds_per_frame=seconds_per_frame, max_frames=max_frames,
            progress_cb=progress_cb, log_cb=log_cb, is_stopped=is_stopped,
            register_process=register_process, unregister_process=unregister_process,
        ))
        index += 1

    for label, paths in standard_photo_tracks or []:
        tracks.append(build_photo_track(index, label, paths, "standard_photos"))
        index += 1

    for label, paths in aerial_photo_tracks or []:
        tracks.append(build_photo_track(index, label, paths, "aerial_photos"))
        index += 1

    if not tracks:
        raise ValueError("No material tracks were provided")

    manifest = {"schema_version": 1, "workflow": "panofusion", "tracks": tracks}
    manifest_path = write_manifest(manifest, work_dir / "panofusion_manifest.json")
    return manifest, manifest_path
