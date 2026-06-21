"""
COLMAP Cubemap Export — renders cubemap faces from fisheye images
using COLMAP-estimated camera parameters.
Matches the algorithm from export_colmap.py for equivalent output.
"""
import os
import struct
import math
import numpy as np
import cv2
from pathlib import Path

PINHOLE_MODEL_IDS = {0, 1, 2, 3, 4, 6, 7}
FISHEYE_MODEL_IDS = {5, 8, 9, 10}
DISTORTED_PINHOLE_MODEL_IDS = {2, 3, 4, 6}
MODEL_PARAM_COUNTS = {
    0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8,
    6: 12, 7: 5, 8: 4, 9: 5, 10: 12,
}


# ═══ Cubemap face config (same as export_colmap.py) ═══

def get_face_configs(W: int):
    W_half = W // 2
    return {
        'front':  (W,      W,      W_half, W_half),
        'right':  (W_half, W,      W_half, W_half),
        'left':   (W_half, W,      0,      W_half),
        'top':    (W,      W_half, W_half, 0),
        'bottom': (W,      W_half, W_half, W_half),
    }

R_faces = {
    'front':  np.eye(3),
    'left':   np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]]),
    'right':  np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]]),
    'top':    np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]]),
    'bottom': np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]),
}


def pinhole_export_strategy(cam: dict, colmap_cam_id: int):
    """Return a distortion-free PINHOLE export strategy for a frame camera."""
    model = cam['model']
    params = cam['params']
    width = int(cam['width'])
    height = int(cam['height'])
    fx, fy, cx, cy = frame_intrinsics(model, params, width, height)
    camera_matrix = np.array(
        [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist = opencv_distortion(model, params)

    undistort = dist is not None and np.any(np.abs(dist) > 1e-12)
    new_camera_matrix = camera_matrix.copy()
    if undistort:
        new_camera_matrix, _ = cv2.getOptimalNewCameraMatrix(
            camera_matrix,
            dist,
            (width, height),
            0.0,
            (width, height),
        )
        if not np.all(np.isfinite(new_camera_matrix)):
            new_camera_matrix = camera_matrix.copy()

    fx_out = float(new_camera_matrix[0, 0])
    fy_out = float(new_camera_matrix[1, 1])
    cx_out = float(new_camera_matrix[0, 2])
    cy_out = float(new_camera_matrix[1, 2])

    return {
        'type': 'pinhole',
        'cid': colmap_cam_id,
        'width': width,
        'height': height,
        'params': (fx_out, fy_out, cx_out, cy_out),
        'undistort': undistort,
        'camera_matrix': camera_matrix,
        'distortion': dist,
        'new_camera_matrix': new_camera_matrix,
        'camera': (1, width, height, fx_out, fy_out, cx_out, cy_out),
    }


def frame_intrinsics(model_id: int, params: list, width: int, height: int):
    if model_id == 0 and len(params) >= 3:  # SIMPLE_PINHOLE
        return float(params[0]), float(params[0]), float(params[1]), float(params[2])
    if model_id == 1 and len(params) >= 4:  # PINHOLE
        return float(params[0]), float(params[1]), float(params[2]), float(params[3])
    if model_id in (2, 3) and len(params) >= 3:  # SIMPLE_RADIAL / RADIAL
        return float(params[0]), float(params[0]), float(params[1]), float(params[2])
    if model_id in (4, 6, 7) and len(params) >= 4:  # OPENCV / FULL_OPENCV / FOV
        return float(params[0]), float(params[1]), float(params[2]), float(params[3])

    focal = float(max(width, height))
    return focal, focal, width * 0.5, height * 0.5


def opencv_distortion(model_id: int, params: list):
    if model_id == 2 and len(params) >= 4:  # SIMPLE_RADIAL
        return np.array([params[3], 0.0, 0.0, 0.0], dtype=np.float64)
    if model_id == 3 and len(params) >= 5:  # RADIAL
        return np.array([params[3], params[4], 0.0, 0.0], dtype=np.float64)
    if model_id == 4 and len(params) >= 8:  # OPENCV
        return np.array([params[4], params[5], params[6], params[7]], dtype=np.float64)
    if model_id == 6 and len(params) >= 12:  # FULL_OPENCV
        return np.array(params[4:12], dtype=np.float64)
    return None


def build_remap_grid(face: str, W: int, fx_src: float, fy_src: float,
                     cx_src: float, cy_src: float, k: list,
                     sensor_w: int, sensor_h: int):
    """Same algorithm as export_colmap.py build_remap_grid."""
    fw, fh, cx, cy = get_face_configs(W)[face]
    u, v = np.meshgrid(np.arange(fw, dtype=np.float32),
                       np.arange(fh, dtype=np.float32))
    f_p = W / 2.0
    X = (u + 0.5 - cx) / f_p
    Y = (v + 0.5 - cy) / f_p
    Z = np.ones_like(u)

    R = R_faces[face]
    Ri = R.T
    Xb = Ri[0, 0] * X + Ri[0, 1] * Y + Ri[0, 2] * Z
    Yb = Ri[1, 0] * X + Ri[1, 1] * Y + Ri[1, 2] * Z
    Zb = Ri[2, 0] * X + Ri[2, 1] * Y + Ri[2, 2] * Z

    r_xy = np.sqrt(Xb**2 + Yb**2)
    theta = np.arctan2(r_xy, Zb)

    # Equidistant projection (same as export_colmap default)
    r_base = theta

    # Radial distortion: r_dist = r_base * (1 + k1*r2 + k2*r4 + k3*r6 + k4*r8)
    r2 = r_base**2
    r_dist = r_base * (1 + k[0]*r2 + k[1]*r2**2 + k[2]*r2**3 + k[3]*r2**4)

    mask = r_xy > 1e-10
    xn = np.zeros_like(theta)
    yn = np.zeros_like(theta)
    xn[mask] = Xb[mask] / r_xy[mask]
    yn[mask] = Yb[mask] / r_xy[mask]

    xd = xn * r_dist
    yd = yn * r_dist

    # Map to sensor pixel coordinates (same as export_colmap)
    mx = (cx_src - 0.5) + xd * fx_src
    my = (cy_src - 0.5) + yd * fy_src

    return mx.astype(np.float32), my.astype(np.float32)


def threaded_remap_and_save(img_src, mx, my, file_path):
    """Render and save a single cubemap face (same as export_colmap)."""
    out = cv2.remap(img_src, mx, my, cv2.INTER_LANCZOS4,
                    borderMode=cv2.BORDER_CONSTANT)
    ok = cv2.imwrite(file_path, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError(f"Failed to write cubemap face: {file_path}")


# ═══ Main export ═══

def export_cubemap_colmap(sparse_dir: str, image_dir: str, output_dir: str,
                           face_size: int = None, add_log=None):
    sparse_path = Path(sparse_dir)
    img_path = Path(image_dir)
    out_images = Path(output_dir) / "images"
    out_sparse = Path(output_dir) / "sparse" / "0"
    out_images.mkdir(parents=True, exist_ok=True)
    out_sparse.mkdir(parents=True, exist_ok=True)

    # COLMAP rig model: images.bin has pre-rig poses. Use TXT export from frames.bin+rigs.bin.
    cameras, images, points3d, frames_map = _read_rig_model(sparse_path)

    if add_log:
        add_log("info", f"COLMAP model: {len(cameras)} cameras, {len(images)} images, {len(points3d)} points")
    if add_log and not points3d:
        add_log("warn", "No points3D found — falling back to image-only export")

    def is_fisheye(model_id):
        return model_id in FISHEYE_MODEL_IDS

    # Build output camera map
    new_cameras = {}  # colmap_cam_id → (model, w, h, fx, fy, cx, cy)
    sensor_strategy = {}  # original_cam_id → {'type':'cubemap'|'pinhole', 'faces':{name:colmap_id}, 'cid':colmap_id}
    colmap_cam_id = 1

    for cid, cam in cameras.items():
        p = cam['params']
        model = cam['model']
        if is_fisheye(model):
            # Cubemap: 5 faces, size = f*2 like Metashape
            calib_f = p[0] if len(p) > 0 else 1042
            W = face_size if face_size else int(round(calib_f * 2.0))
            if W % 2 != 0:
                W += 1
            strategy = {'type': 'cubemap', 'faces': {}, 'W': W}
            face_cfgs = get_face_configs(W)
            for face_name, (fw, fh, fcx, fcy) in face_cfgs.items():
                new_cameras[colmap_cam_id] = (1, fw, fh, W/2.0, W/2.0, fcx, fcy)
                strategy['faces'][face_name] = colmap_cam_id
                colmap_cam_id += 1
        elif model in PINHOLE_MODEL_IDS:
            # LightField Studio and most 3DGS trainers expect distortion-free
            # cameras. Frame images are undistorted when needed and always
            # exported as COLMAP PINHOLE.
            w, h = cam['width'], cam['height']
            if not p:
                raise RuntimeError(f"Camera {cid} has no intrinsic parameters")
            strategy = pinhole_export_strategy(cam, colmap_cam_id)
            new_cameras[colmap_cam_id] = strategy['camera']
            colmap_cam_id += 1
        else:
            raise RuntimeError(f"Unsupported COLMAP camera model id {model} for camera {cid}")
        sensor_strategy[cid] = strategy

    new_images = []
    colmap_img_id = 1
    grid_cache = {}
    point_refs = {pid: [] for pid in points3d}
    cubemap_image_count = 0
    frame_image_count = 0
    undistorted_frame_count = 0

    total = len(images)
    for idx, (iid, img) in enumerate(sorted(images.items())):
        cid = img['camera_id']
        if cid not in sensor_strategy:
            continue
        strategy = sensor_strategy[cid]
        name = img['name']

        qw, qx, qy, qz = img['qvec']
        tx, ty, tz = img['tvec']

        # Build rotation matrix from quaternion
        R_w2c = np.array([
            [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
            [2*qx*qy + 2*qz*qw, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
            [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx**2 - 2*qy**2],
        ])
        t_w2c = np.array([tx, ty, tz], dtype=np.float64)

        # Load source image
        src_path = img_path / name
        if not src_path.exists():
            # Try alternate path: track_id/side/frame_id.jpg
            parts = Path(name).parts
            if len(parts) >= 2:
                alt = img_path / name
                if alt.exists():
                    src_path = alt
            if not src_path.exists():
                raise RuntimeError(f"Source image missing for registered image: {name}")

        img_src = cv2.imread(str(src_path))
        if img_src is None:
            raise RuntimeError(f"Failed to read source image: {src_path}")

        base_name = f"{iid:05d}_{Path(name).stem}"

        if strategy['type'] == 'cubemap':
            cam = cameras[cid]
            p = cam['params']
            W = strategy['W']
            fx_src = p[0]
            fy_src = p[1] if len(p) > 1 else fx_src
            cx_src = p[2] if len(p) > 2 else cam['width'] / 2.0
            cy_src = p[3] if len(p) > 3 else cam['height'] / 2.0
            k = list(p[4:8]) if len(p) > 4 else [0, 0, 0, 0]
            while len(k) < 4:
                k.append(0.0)
            sensor_w = cam['width']
            sensor_h = cam['height']

            # Get observed 3D point IDs from original COLMAP image
            observed_pids = set()
            for _, _, pid in img.get('pts2d', []):
                if pid in points3d:
                    observed_pids.add(pid)

            for face_name in ['front', 'left', 'right', 'top', 'bottom']:
                cid_out = strategy['faces'][face_name]
                out_name = f"cube_{face_name}_{base_name}.jpg"
                if not out_name.lower().endswith('.jpg'):
                    out_name += '.jpg'

                # Face camera params
                fw, fh, fcx, fcy = get_face_configs(W)[face_name]
                fx = fy = W / 2.0

                R_f = R_faces[face_name]
                rf = R_f @ R_w2c
                q = _rot_to_quat_np(rf)
                tf = R_f @ t_w2c

                # Project observed 3D points into this cubemap face
                pts2d_out = []
                for pid in observed_pids:
                    pt = points3d[pid]
                    uv = _project_to_pinhole(pt['xyz'], rf, tf, fx, fy, fcx, fcy, fw, fh)
                    if uv is not None:
                        point_refs[pid].append((colmap_img_id, len(pts2d_out)))
                        pts2d_out.append((uv[0], uv[1], pid))

                new_images.append({
                    'id': colmap_img_id,
                    'qvec': (q[0], q[1], q[2], q[3]),
                    'tvec': (float(tf[0]), float(tf[1]), float(tf[2])),
                    'camera_id': cid_out,
                    'name': out_name,
                    'pts2d': pts2d_out,
                })

                # Render face
                cache_key = (cid, W, face_name)
                if cache_key not in grid_cache:
                    mx, my = build_remap_grid(face_name, W, fx_src, fy_src, cx_src, cy_src, k, sensor_w, sensor_h)
                    grid_cache[cache_key] = (mx, my)
                mx, my = grid_cache[cache_key]
                threaded_remap_and_save(img_src.copy(), mx, my, str(out_images / out_name))

                colmap_img_id += 1
                cubemap_image_count += 1
        else:
            # Frame image: undistort if the source camera has distortion, then
            # keep the original pose with a distortion-free PINHOLE camera.
            cid_out = strategy['cid']
            fw = strategy['width']
            fh = strategy['height']
            fx, fy, fcx, fcy = strategy['params']
            out_name = f"frame_{base_name}.jpg"
            if not out_name.lower().endswith('.jpg'):
                out_name += '.jpg'

            frame_img = img_src
            if strategy.get('undistort'):
                frame_img = cv2.undistort(
                    img_src,
                    strategy['camera_matrix'],
                    strategy['distortion'],
                    None,
                    strategy['new_camera_matrix'],
                )
                undistorted_frame_count += 1

            ok = cv2.imwrite(str(out_images / out_name), frame_img,
                             [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise RuntimeError(f"Failed to write frame image: {out_name}")

            observed_pids = []
            seen_pids = set()
            for _, _, pid in img.get('pts2d', []):
                if pid in points3d and pid not in seen_pids:
                    observed_pids.append(pid)
                    seen_pids.add(pid)

            pts2d_out = []
            for pid in observed_pids:
                pt = points3d[pid]
                uv = _project_to_pinhole(pt['xyz'], R_w2c, t_w2c, fx, fy, fcx, fcy, fw, fh)
                if uv is not None:
                    point_refs[pid].append((colmap_img_id, len(pts2d_out)))
                    pts2d_out.append((uv[0], uv[1], pid))

            new_images.append({
                'id': colmap_img_id,
                'qvec': (qw, qx, qy, qz),
                'tvec': (tx, ty, tz),
                'camera_id': cid_out,
                'name': out_name,
                'pts2d': pts2d_out,
            })
            colmap_img_id += 1
            frame_image_count += 1

        if add_log and (idx + 1) % 50 == 0:
            add_log("info", f"  处理中 [{idx+1}/{total}]")

    new_points3d = {
        pid: {**points3d[pid], "refs": refs}
        for pid, refs in point_refs.items()
        if refs
    }

    # Write COLMAP files
    _write_cameras_bin(out_sparse / "cameras.bin", new_cameras)
    _write_images_bin(out_sparse / "images.bin", new_images)
    _write_points3d_bin(out_sparse / "points3D.bin", new_points3d)

    if add_log:
        add_log("info", f"Cubemap export: {len(new_images)} images, {len(new_cameras)} cameras, {len(new_points3d)} points")

    return {
        "source_images": len(images),
        "output_images": len(new_images),
        "output_cameras": len(new_cameras),
        "output_points3D": len(new_points3d),
        "cubemap_images": cubemap_image_count,
        "frame_images": frame_image_count,
        "undistorted_frame_images": undistorted_frame_count,
    }


# ═══ COLMAP binary I/O ═══



    if norm > 0:
        q /= norm
    return tuple(float(v) for v in q)

def _read_rig_model(sparse_path):
    import subprocess, shutil
    from pathlib import Path
    sparse_path = Path(sparse_path)
    txt_dir = sparse_path.parent / "_txt_export"
    import shutil
    if txt_dir.exists():
        shutil.rmtree(txt_dir)
    txt_dir.mkdir(parents=True, exist_ok=True)
    
    colmap_exe = _find_colmap_exe()
    result = subprocess.run(
        [colmap_exe, "model_converter", "--input_path", str(sparse_path),
         "--output_path", str(txt_dir), "--output_type", "TXT"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"COLMAP model_converter failed: {detail[:800]}")
    for required in ("cameras.txt", "images.txt"):
        if not (txt_dir / required).exists():
            raise RuntimeError(f"COLMAP model_converter did not produce {required}")
    
    # Read cameras
    cameras = {}
    model_map = {"SIMPLE_PINHOLE":0,"PINHOLE":1,"SIMPLE_RADIAL":2,"RADIAL":3,
                 "OPENCV":4,"OPENCV_FISHEYE":5,"FULL_OPENCV":6,"FOV":7,
                 "SIMPLE_RADIAL_FISHEYE":8,"RADIAL_FISHEYE":9,"THIN_PRISM_FISHEYE":10}
    with open(txt_dir / "cameras.txt") as f:
        for line in f:
            if line.startswith("#"): continue
            parts = line.split()
            cid = int(parts[0])
            model_id = model_map.get(parts[1], 5)
            w = int(parts[2]); h = int(parts[3])
            params = [float(x) for x in parts[4:]]
            cameras[cid] = {"model": model_id, "width": w, "height": h, "params": params}
    
    # Read rigs: cam_id -> (q_rel, t_rel)
    rig_rel = {}
    rig_txt = txt_dir / "rigs.txt"
    if rig_txt.exists():
        with open(rig_txt) as f:
            for line in f:
                if line.startswith("#"): continue
                parts = line.split()
                num_sensors = int(parts[1])
                idx = 2
                ref_type = parts[idx]; idx += 1
                ref_id = int(parts[idx]); idx += 1
                for _ in range(num_sensors - 1):
                    s_type = parts[idx]; idx += 1
                    s_id = int(parts[idx]); idx += 1
                    has_pose = int(parts[idx]); idx += 1
                    if has_pose:
                        q = (float(parts[idx]), float(parts[idx+1]), float(parts[idx+2]), float(parts[idx+3]))
                        idx += 4
                        t = (float(parts[idx]), float(parts[idx+1]), float(parts[idx+2]))
                        idx += 3
                        rig_rel[s_id] = (q, t)
    
    # Read frames: data_id -> (frame_q, frame_t, cam_id, is_ref)
    frame_poses = {}  # data_id -> (q, t, cam_id)
    with open(txt_dir / "frames.txt") as f:
        for line in f:
            if line.startswith("#"): continue
            parts = line.split()
            fq = (float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]))
            ft = (float(parts[6]), float(parts[7]), float(parts[8]))
            num_data = int(parts[9])
            idx = 10
            for i in range(num_data):
                s_type = parts[idx]; idx += 1
                s_id = int(parts[idx]); idx += 1
                d_id = int(parts[idx]); idx += 1
                is_ref = (i == 0)  # First camera is ref sensor
                if is_ref:
                    frame_poses[d_id] = (fq, ft, s_id)
                elif s_id in rig_rel and d_id not in frame_poses:
                    # frames.txt stores RIG_FROM_WORLD and rigs.txt stores
                    # SENSOR_FROM_RIG, so compose SENSOR_FROM_WORLD.
                    R_f = _quat_to_rot_np(*fq)
                    rq, rt = rig_rel[s_id]
                    R_rel = _quat_to_rot_np(*rq)
                    R = R_rel @ R_f
                    t_vec = R_rel @ np.array(ft) + np.array(rt)
                    q = _rot_to_quat_np(R)
                    frame_poses[d_id] = (q, (float(t_vec[0]), float(t_vec[1]), float(t_vec[2])), s_id)
    
    # Read images (use frame_poses for rig images, original pose for non-rig)
    images = {}
    with open(txt_dir / "images.txt") as f:
        lines = [l.strip() for l in f if not l.startswith("#") and l.strip()]
        i = 0
        while i < len(lines):
            parts = lines[i].split()
            iid = int(parts[0])
            orig_q = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
            orig_t = (float(parts[5]), float(parts[6]), float(parts[7]))
            cam_id = int(parts[8])
            name = parts[9]
            pts2d = []
            if i + 1 < len(lines):
                pts_parts = lines[i+1].split()
                if len(pts_parts) >= 3:
                    try:
                        float(pts_parts[0])
                        for j in range(0, len(pts_parts), 3):
                            if j+2 < len(pts_parts):
                                pts2d.append((float(pts_parts[j]), float(pts_parts[j+1]), int(pts_parts[j+2])))
                        i += 1
                    except ValueError:
                        pass
            i += 1
            # Use frame-computed pose if available, otherwise original
            use_q, use_t = orig_q, orig_t
            if iid in frame_poses:
                use_q, use_t, _ = frame_poses[iid]
            images[iid] = {"qvec": use_q, "tvec": use_t, "camera_id": cam_id, "name": name, "pts2d": pts2d}
    
    # Read points3D
    points3d = {}
    pts_file = txt_dir / "points3D.txt"
    if pts_file.exists():
        with open(pts_file) as f:
            for line in f:
                if line.startswith("#"): continue
                parts = line.split()
                pid = int(parts[0])
                xyz = (float(parts[1]), float(parts[2]), float(parts[3]))
                rgb = (int(parts[4]), int(parts[5]), int(parts[6]))
                err = float(parts[7])
                points3d[pid] = {"xyz": xyz, "rgb": rgb, "error": err}
    
    if txt_dir.exists():
        shutil.rmtree(txt_dir)
    return cameras, images, points3d, frame_poses


def _find_colmap_exe():
    from config import find_colmap_exe
    return find_colmap_exe()


def _quat_to_rot_np(qw, qx, qy, qz):
    return np.array([
        [1-2*qy**2-2*qz**2, 2*qx*qy-2*qz*qw, 2*qx*qz+2*qy*qw],
        [2*qx*qy+2*qz*qw, 1-2*qx**2-2*qz**2, 2*qy*qz-2*qx*qw],
        [2*qx*qz-2*qy*qw, 2*qy*qz+2*qx*qw, 1-2*qx**2-2*qy**2],
    ])

def _rot_to_quat_np(R):
    """Return quaternion as COLMAP format (qw, qx, qy, qz)."""
    R = np.asarray(R, dtype=np.float64)
    tr = R[0,0] + R[1,1] + R[2,2]
    if tr > 0:
        s = 2 * math.sqrt(tr + 1)
        q = (0.25*s, (R[2,1]-R[1,2])/s, (R[0,2]-R[2,0])/s, (R[1,0]-R[0,1])/s)
    elif R[0,0] > R[1,1] and R[0,0] > R[2,2]:
        s = 2 * math.sqrt(1+R[0,0]-R[1,1]-R[2,2])
        q = ((R[2,1]-R[1,2])/s, 0.25*s, (R[0,1]+R[1,0])/s, (R[0,2]+R[2,0])/s)
    elif R[1,1] > R[2,2]:
        s = 2 * math.sqrt(1+R[1,1]-R[0,0]-R[2,2])
        q = ((R[0,2]-R[2,0])/s, (R[0,1]+R[1,0])/s, 0.25*s, (R[1,2]+R[2,1])/s)
    else:
        s = 2 * math.sqrt(1+R[2,2]-R[0,0]-R[1,1])
        q = ((R[1,0]-R[0,1])/s, (R[0,2]+R[2,0])/s, (R[1,2]+R[2,1])/s, 0.25*s)
    q = np.array(q, dtype=np.float64)
    norm = np.linalg.norm(q)
    if norm > 0:
        q /= norm
    return tuple(float(v) for v in q)

def _read_cameras_bin(path):
    cameras = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            cid = struct.unpack("<I", f.read(4))[0]
            model = struct.unpack("<I", f.read(4))[0]
            w = struct.unpack("<Q", f.read(8))[0]
            h = struct.unpack("<Q", f.read(8))[0]
            n_params = MODEL_PARAM_COUNTS.get(model, 4)
            params = struct.unpack(f"<{n_params}d", f.read(8 * n_params))
            cameras[cid] = {'model': model, 'width': w, 'height': h,
                           'params': list(params)}
    return cameras



def _read_points3d_bin(path):
    points = {}
    if not path.exists():
        return points
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            pid = struct.unpack("<Q", f.read(8))[0]
            x, y, z = struct.unpack("<ddd", f.read(24))
            r, g, b = struct.unpack("<BBB", f.read(3))
            err = struct.unpack("<d", f.read(8))[0]
            track_len = struct.unpack("<Q", f.read(8))[0]
            # Each track ref: image_id(uint32=4) + point2D_idx(uint32=4) = 8 bytes
            f.seek(track_len * 8, 1)
            points[pid] = {'xyz': (x, y, z), 'rgb': (r, g, b), 'error': err}
    return points

def _read_images_bin(path):
    images = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            iid = struct.unpack("<I", f.read(4))[0]
            qw, qx, qy, qz = struct.unpack("<dddd", f.read(32))
            tx, ty, tz = struct.unpack("<ddd", f.read(24))
            cid = struct.unpack("<I", f.read(4))[0]
            name = b""
            while True:
                ch = f.read(1)
                if ch == b'\0': break
                name += ch
            n_pts = struct.unpack("<Q", f.read(8))[0]
            pts2d = []
            for _ in range(n_pts):
                px = struct.unpack("<d", f.read(8))[0]
                py = struct.unpack("<d", f.read(8))[0]
                pid = struct.unpack("<Q", f.read(8))[0]
                pts2d.append((px, py, pid))
            images[iid] = {'qvec': (qw, qx, qy, qz), 'tvec': (tx, ty, tz),
                          'camera_id': cid, 'name': name.decode(), 'pts2d': pts2d}
    return images


def _write_cameras_bin(path, cameras):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(cameras)))
        for cid in sorted(cameras):
            c = cameras[cid]  # (model, width, height, params...)
            f.write(struct.pack("<I", cid))
            f.write(struct.pack("<I", c[0]))  # model
            f.write(struct.pack("<Q", c[1]))  # width
            f.write(struct.pack("<Q", c[2]))  # height
            expected = MODEL_PARAM_COUNTS.get(c[0])
            if expected is not None and len(c[3:]) != expected:
                raise RuntimeError(f"Camera {cid} model {c[0]} expects {expected} params, got {len(c[3:])}")
            for p in c[3:]:
                f.write(struct.pack("<d", p))


def _write_images_bin(path, images):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(images)))
        for img in sorted(images, key=lambda x: x['id']):
            f.write(struct.pack("<I", img['id']))
            q = img['qvec']
            f.write(struct.pack("<dddd", q[0], q[1], q[2], q[3]))
            t = img['tvec']
            f.write(struct.pack("<ddd", t[0], t[1], t[2]))
            f.write(struct.pack("<I", img['camera_id']))
            f.write(img['name'].encode() + b'\0')
            pts = img.get('pts2d', [])
            f.write(struct.pack("<Q", len(pts)))
            for px, py, pid in pts:
                f.write(struct.pack("<ddQ", px, py, pid))


def _write_points3d_bin(path, points):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(points)))
        for pid in sorted(points):
            p = points[pid]
            x, y, z = p["xyz"]
            r, g, b = p.get("rgb", (255, 255, 255))
            refs = p.get("refs", [])
            f.write(struct.pack("<Q", int(pid)))
            f.write(struct.pack("<ddd", float(x), float(y), float(z)))
            f.write(struct.pack("<BBB", int(r), int(g), int(b)))
            f.write(struct.pack("<d", float(p.get("error", 0.0))))
            f.write(struct.pack("<Q", len(refs)))
            for image_id, point2d_idx in refs:
                f.write(struct.pack("<II", int(image_id), int(point2d_idx)))


def _project_to_pinhole(point_xyz, R, T, fx, fy, cx, cy, w, h):
    """Project a 3D point into a pinhole camera, returns (u,v) or None."""
    X = np.array(point_xyz, dtype=np.float64)
    pc = R @ X + T
    if pc[2] <= 1e-8:
        return None
    u = fx * (pc[0] / pc[2]) + cx
    v = fy * (pc[1] / pc[2]) + cy
    if 0 <= u < w and 0 <= v < h:
        return (float(u), float(v))
    return None


def _rot_to_quat(R):
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = 2 * math.sqrt(tr + 1)
        return ((R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s,
                (R[1, 0] - R[0, 1]) / s, 0.25 * s)
    if R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2 * math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2])
        return (0.25 * s, (R[0, 1] + R[1, 0]) / s,
                (R[0, 2] + R[2, 0]) / s, (R[2, 1] - R[1, 2]) / s)
    if R[1, 1] > R[2, 2]:
        s = 2 * math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2])
        return ((R[0, 1] + R[1, 0]) / s, 0.25 * s,
                (R[1, 2] + R[2, 1]) / s, (R[0, 2] - R[2, 0]) / s)
    s = 2 * math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1])
    return ((R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s,
            0.25 * s, (R[1, 0] - R[0, 1]) / s)
