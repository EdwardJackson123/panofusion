"""
Ground alignment for exported COLMAP models.

This applies a global rigid transform to points3D.bin and images.bin so the
model itself is aligned, instead of compensating in the viewer.
"""
from __future__ import annotations

import json
import math
import shutil
import struct
from pathlib import Path

import numpy as np


TARGET_UP_BY_AXIS = {
    "+Y": np.array([0.0, 1.0, 0.0], dtype=np.float64),
    "-Y": np.array([0.0, -1.0, 0.0], dtype=np.float64),
    "+Z": np.array([0.0, 0.0, 1.0], dtype=np.float64),
    "-Z": np.array([0.0, 0.0, -1.0], dtype=np.float64),
    "+X": np.array([1.0, 0.0, 0.0], dtype=np.float64),
    "-X": np.array([-1.0, 0.0, 0.0], dtype=np.float64),
}


def apply_ground_alignment(
    model_dir: str | Path,
    *,
    up_axis: str = "+Y",
    add_log=None,
    force: bool = False,
    backup_dir: str | Path | None = None,
) -> dict:
    model_path = Path(model_dir)
    points_path = model_path / "points3D.bin"
    images_path = model_path / "images.bin"
    meta_path = model_path / "ground_alignment.json"

    if not force and meta_path.exists():
        return {"enabled": True, "applied": False, "reason": "already_aligned"}
    if not points_path.exists():
        return {"enabled": True, "applied": False, "reason": "points3D_missing"}
    if not images_path.exists():
        return {"enabled": True, "applied": False, "reason": "images_missing"}

    points = _read_points3d_bin(points_path)
    images = _read_images_bin(images_path)
    if len(points) < 50:
        return {"enabled": True, "applied": False, "reason": "not_enough_points", "point_count": len(points)}

    xyz = np.array([item["xyz"] for item in points.values()], dtype=np.float64)
    camera_centers = _camera_centers(images)
    target_up = TARGET_UP_BY_AXIS.get(up_axis, TARGET_UP_BY_AXIS["+Y"])
    rotation, translation, stats = _estimate_ground_transform(xyz, camera_centers, target_up)

    if backup_dir is not None:
        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)
        for name in ("cameras.bin", "images.bin", "points3D.bin"):
            src = model_path / name
            if src.exists():
                shutil.copy2(src, backup_path / name)

    for item in points.values():
        item["xyz"] = _transform_point(np.asarray(item["xyz"], dtype=np.float64), rotation, translation)

    for item in images.values():
        r_cw = _quat_to_rot_np(*item["qvec"])
        t_cw = np.asarray(item["tvec"], dtype=np.float64)
        new_r_cw = r_cw @ rotation.T
        new_t_cw = t_cw - new_r_cw @ translation
        item["qvec"] = _rot_to_quat_np(new_r_cw)
        item["tvec"] = tuple(float(v) for v in new_t_cw)

    _write_points3d_bin(points_path, points)
    _write_images_bin(images_path, images)

    result = {
        "enabled": True,
        "applied": True,
        "up_axis": up_axis,
        "target_up_colmap": target_up.tolist(),
        "point_count": len(points),
        "image_count": len(images),
        **stats,
        "rotation": rotation.tolist(),
        "translation": translation.tolist(),
    }
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if add_log:
        angle = stats.get("rotation_degrees", 0.0)
        inliers = stats.get("inlier_count", 0)
        add_log("info", f"地面对齐完成: 旋转 {angle:.2f}°, 地面内点 {inliers}")

    return result


def _estimate_ground_transform(points: np.ndarray, camera_centers: np.ndarray, target_up: np.ndarray):
    core = _robust_core(points)
    up_guess = _estimate_up_from_cameras(camera_centers, core)
    ground_normal, inlier_mask, threshold, method = _fit_ground_plane(core, up_guess)

    if ground_normal is None:
        ground_normal = up_guess if up_guess is not None else target_up.copy()
        inlier_mask = np.ones(len(core), dtype=bool)
        method = "fallback"

    ground_normal = _normalize(ground_normal)
    if np.dot(ground_normal, target_up) < 0:
        ground_normal = -ground_normal

    rotation = _rotation_between_vectors(ground_normal, target_up)
    inlier_points = core[inlier_mask] if inlier_mask is not None and np.any(inlier_mask) else core
    rotated_points = points @ rotation.T
    rotated_inliers = inlier_points @ rotation.T

    ground_level = float(np.median(rotated_inliers @ target_up))
    ground_translation = -ground_level * target_up
    leveled = rotated_points + ground_translation

    lo = np.quantile(leveled, 0.05, axis=0)
    hi = np.quantile(leveled, 0.95, axis=0)
    robust_center = (lo + hi) * 0.5
    horizontal_center = robust_center - target_up * float(np.dot(robust_center, target_up))
    translation = ground_translation - horizontal_center

    dot_value = float(np.clip(np.dot(ground_normal, target_up), -1.0, 1.0))
    stats = {
        "method": method,
        "ground_normal": ground_normal.tolist(),
        "up_guess": up_guess.tolist() if up_guess is not None else None,
        "threshold": float(threshold),
        "inlier_count": int(np.count_nonzero(inlier_mask)) if inlier_mask is not None else 0,
        "core_point_count": int(len(core)),
        "ground_level_before_translation": ground_level,
        "rotation_degrees": math.degrees(math.acos(dot_value)),
    }
    return rotation, translation, stats


def _robust_core(points: np.ndarray) -> np.ndarray:
    if len(points) < 200:
        return points
    lo = np.quantile(points, 0.015, axis=0)
    hi = np.quantile(points, 0.985, axis=0)
    mask = np.all((points >= lo) & (points <= hi), axis=1)
    core = points[mask]
    return core if len(core) >= 50 else points


def _estimate_up_from_cameras(camera_centers: np.ndarray, core: np.ndarray):
    if camera_centers is None or len(camera_centers) < 8:
        return None

    centered = camera_centers - np.mean(camera_centers, axis=0)
    if not np.all(np.isfinite(centered)):
        return None

    cov = np.cov(centered.T)
    values, vectors = np.linalg.eigh(cov)
    if not np.all(np.isfinite(values)):
        return None

    up = vectors[:, int(np.argmin(values))]
    up = _normalize(up)
    if np.linalg.norm(up) < 1e-9:
        return None

    # Pick the sign where cameras are generally above the bulk of points.
    if float(np.median(camera_centers @ up)) < float(np.median(core @ up)):
        up = -up
    return up


def _fit_ground_plane(core: np.ndarray, up_guess: np.ndarray | None):
    rng = np.random.default_rng(7)
    candidates = core
    method = "ransac"

    if up_guess is not None and len(core) >= 200:
        projections = core @ up_guess
        cutoff = np.quantile(projections, 0.45)
        lower = core[projections <= cutoff]
        if len(lower) >= 50:
            candidates = lower
            method = "camera_guided_ransac"

    if len(candidates) > 20000:
        candidates = candidates[rng.choice(len(candidates), 20000, replace=False)]

    score_points = core
    if len(score_points) > 40000:
        score_points = score_points[rng.choice(len(score_points), 40000, replace=False)]

    q02 = np.quantile(core, 0.02, axis=0)
    q98 = np.quantile(core, 0.98, axis=0)
    diagonal = float(np.linalg.norm(q98 - q02))
    threshold = max(diagonal * 0.006, 1e-4)

    best_normal = None
    best_offset = 0.0
    best_count = -1
    iterations = 1800 if len(candidates) >= 1000 else 700

    if len(candidates) < 3:
        return None, None, threshold, "not_enough_candidates"

    for _ in range(iterations):
        sample_ids = rng.choice(len(candidates), 3, replace=False)
        a, b, c = candidates[sample_ids]
        normal = np.cross(b - a, c - a)
        normal_norm = float(np.linalg.norm(normal))
        if normal_norm < 1e-9:
            continue
        normal /= normal_norm

        if up_guess is not None and abs(float(np.dot(normal, up_guess))) < 0.35:
            continue

        offset = float(np.dot(normal, a))
        distances = np.abs(score_points @ normal - offset)
        count = int(np.count_nonzero(distances < threshold))
        if count > best_count:
            best_count = count
            best_normal = normal.copy()
            best_offset = offset

    if best_normal is None:
        return None, None, threshold, "ransac_failed"

    if up_guess is not None and np.dot(best_normal, up_guess) < 0:
        best_normal = -best_normal
        best_offset = -best_offset

    inlier_mask = np.abs(core @ best_normal - best_offset) < threshold * 1.6
    if np.count_nonzero(inlier_mask) >= 8:
        inliers = core[inlier_mask]
        centered = inliers - np.mean(inliers, axis=0)
        _, vectors = np.linalg.eigh(np.cov(centered.T))
        refined = vectors[:, 0]
        if up_guess is not None and np.dot(refined, up_guess) < 0:
            refined = -refined
        best_normal = _normalize(refined)

    return best_normal, inlier_mask, threshold, method


def _rotation_between_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source = _normalize(source)
    target = _normalize(target)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if dot > 1.0 - 1e-10:
        return np.eye(3, dtype=np.float64)
    if dot < -1.0 + 1e-10:
        axis = np.cross(source, np.array([1.0, 0.0, 0.0], dtype=np.float64))
        if np.linalg.norm(axis) < 1e-8:
            axis = np.cross(source, np.array([0.0, 0.0, 1.0], dtype=np.float64))
        axis = _normalize(axis)
        return _axis_angle_to_matrix(axis, math.pi)

    axis = np.cross(source, target)
    sine = float(np.linalg.norm(axis))
    axis /= sine
    k = _skew(axis)
    return np.eye(3, dtype=np.float64) + k * sine + (k @ k) * (1.0 - dot)


def _axis_angle_to_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = _normalize(axis)
    k = _skew(axis)
    return np.eye(3, dtype=np.float64) + math.sin(angle) * k + (1.0 - math.cos(angle)) * (k @ k)


def _skew(axis: np.ndarray) -> np.ndarray:
    x, y, z = axis
    return np.array(
        [
            [0.0, -z, y],
            [z, 0.0, -x],
            [-y, x, 0.0],
        ],
        dtype=np.float64,
    )


def _normalize(value: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(value))
    if norm <= 1e-12:
        return value
    return value / norm


def _transform_point(point: np.ndarray, rotation: np.ndarray, translation: np.ndarray):
    transformed = rotation @ point + translation
    return tuple(float(v) for v in transformed)


def _camera_centers(images: dict[int, dict]) -> np.ndarray:
    centers = []
    for image in images.values():
        rotation = _quat_to_rot_np(*image["qvec"])
        tvec = np.asarray(image["tvec"], dtype=np.float64)
        centers.append(-rotation.T @ tvec)
    return np.asarray(centers, dtype=np.float64)


def _read_null_terminated(handle) -> str:
    data = bytearray()
    while True:
        ch = handle.read(1)
        if not ch or ch == b"\0":
            break
        data.extend(ch)
    return data.decode("utf-8", errors="replace")


def _read_points3d_bin(path: Path) -> dict[int, dict]:
    points = {}
    with open(path, "rb") as handle:
        count_data = handle.read(8)
        if len(count_data) < 8:
            return points
        count = struct.unpack("<Q", count_data)[0]
        for _ in range(count):
            point_id = struct.unpack("<Q", handle.read(8))[0]
            xyz = struct.unpack("<ddd", handle.read(24))
            rgb = struct.unpack("<BBB", handle.read(3))
            error = struct.unpack("<d", handle.read(8))[0]
            track_len = struct.unpack("<Q", handle.read(8))[0]
            refs = [struct.unpack("<II", handle.read(8)) for _ in range(track_len)]
            points[point_id] = {"xyz": xyz, "rgb": rgb, "error": error, "refs": refs}
    return points


def _write_points3d_bin(path: Path, points: dict[int, dict]):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "wb") as handle:
        handle.write(struct.pack("<Q", len(points)))
        for point_id in sorted(points):
            point = points[point_id]
            handle.write(struct.pack("<Q", int(point_id)))
            handle.write(struct.pack("<ddd", *[float(v) for v in point["xyz"]]))
            r, g, b = point.get("rgb", (255, 255, 255))
            handle.write(struct.pack("<BBB", int(r), int(g), int(b)))
            handle.write(struct.pack("<d", float(point.get("error", 0.0))))
            refs = point.get("refs", [])
            handle.write(struct.pack("<Q", len(refs)))
            for image_id, point2d_idx in refs:
                handle.write(struct.pack("<II", int(image_id), int(point2d_idx)))
    tmp_path.replace(path)


def _read_images_bin(path: Path) -> dict[int, dict]:
    images = {}
    with open(path, "rb") as handle:
        count_data = handle.read(8)
        if len(count_data) < 8:
            return images
        count = struct.unpack("<Q", count_data)[0]
        for _ in range(count):
            image_id = struct.unpack("<I", handle.read(4))[0]
            qvec = struct.unpack("<dddd", handle.read(32))
            tvec = struct.unpack("<ddd", handle.read(24))
            camera_id = struct.unpack("<I", handle.read(4))[0]
            name = _read_null_terminated(handle)
            point_count = struct.unpack("<Q", handle.read(8))[0]
            pts2d = [struct.unpack("<ddQ", handle.read(24)) for _ in range(point_count)]
            images[image_id] = {
                "id": image_id,
                "qvec": qvec,
                "tvec": tvec,
                "camera_id": camera_id,
                "name": name,
                "pts2d": pts2d,
            }
    return images


def _write_images_bin(path: Path, images: dict[int, dict]):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "wb") as handle:
        handle.write(struct.pack("<Q", len(images)))
        for image_id in sorted(images):
            image = images[image_id]
            handle.write(struct.pack("<I", int(image_id)))
            handle.write(struct.pack("<dddd", *[float(v) for v in image["qvec"]]))
            handle.write(struct.pack("<ddd", *[float(v) for v in image["tvec"]]))
            handle.write(struct.pack("<I", int(image["camera_id"])))
            handle.write(image["name"].encode("utf-8") + b"\0")
            pts2d = image.get("pts2d", [])
            handle.write(struct.pack("<Q", len(pts2d)))
            for x, y, point3d_id in pts2d:
                handle.write(struct.pack("<ddQ", float(x), float(y), int(point3d_id)))
    tmp_path.replace(path)


def _quat_to_rot_np(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    return np.array(
        [
            [1 - 2 * qy**2 - 2 * qz**2, 2 * qx * qy - 2 * qz * qw, 2 * qx * qz + 2 * qy * qw],
            [2 * qx * qy + 2 * qz * qw, 1 - 2 * qx**2 - 2 * qz**2, 2 * qy * qz - 2 * qx * qw],
            [2 * qx * qz - 2 * qy * qw, 2 * qy * qz + 2 * qx * qw, 1 - 2 * qx**2 - 2 * qy**2],
        ],
        dtype=np.float64,
    )


def _rot_to_quat_np(rotation: np.ndarray):
    r = np.asarray(rotation, dtype=np.float64)
    trace = float(r[0, 0] + r[1, 1] + r[2, 2])
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        quat = (0.25 * s, (r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s)
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = 2.0 * math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])
        quat = ((r[2, 1] - r[1, 2]) / s, 0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s)
    elif r[1, 1] > r[2, 2]:
        s = 2.0 * math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])
        quat = ((r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s)
    else:
        s = 2.0 * math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])
        quat = ((r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s)

    quat_array = np.asarray(quat, dtype=np.float64)
    norm = float(np.linalg.norm(quat_array))
    if norm > 0:
        quat_array /= norm
    return tuple(float(v) for v in quat_array)
