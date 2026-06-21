"""
3D Viewer API routes — serve point cloud data
"""
import struct
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import PROJECTS_DIR
from routes.project_names import project_dir

router = APIRouter()


CAMERA_MODEL_PARAM_COUNTS = {
    0: 3,   # SIMPLE_PINHOLE
    1: 4,   # PINHOLE
    2: 4,   # SIMPLE_RADIAL
    3: 5,   # RADIAL
    4: 8,   # OPENCV
    5: 8,   # OPENCV_FISHEYE
    6: 12,  # FULL_OPENCV
    7: 5,   # FOV
    8: 4,   # SIMPLE_RADIAL_FISHEYE
    9: 5,   # RADIAL_FISHEYE
    10: 12, # THIN_PRISM_FISHEYE
}


def read_colmap_bin(path: Path):
    """Read a COLMAP binary file and return list of records"""
    if not path.exists():
        return None
    with open(path, "rb") as f:
        data = f.read()
    return data


def qvec_to_rotmat(qvec):
    qw, qx, qy, qz = qvec
    return (
        (
            1 - 2 * qy * qy - 2 * qz * qz,
            2 * qx * qy - 2 * qw * qz,
            2 * qz * qx + 2 * qw * qy,
        ),
        (
            2 * qx * qy + 2 * qw * qz,
            1 - 2 * qx * qx - 2 * qz * qz,
            2 * qy * qz - 2 * qw * qx,
        ),
        (
            2 * qz * qx - 2 * qw * qy,
            2 * qy * qz + 2 * qw * qx,
            1 - 2 * qx * qx - 2 * qy * qy,
        ),
    )


def mat_transpose_vec_mul(mat, vec):
    return (
        mat[0][0] * vec[0] + mat[1][0] * vec[1] + mat[2][0] * vec[2],
        mat[0][1] * vec[0] + mat[1][1] * vec[1] + mat[2][1] * vec[2],
        mat[0][2] * vec[0] + mat[1][2] * vec[1] + mat[2][2] * vec[2],
    )


def parse_cameras_bin(data: bytes):
    if data is None or len(data) < 8:
        return {}

    data_len = len(data)
    pos = 0
    num_cameras = struct.unpack_from("<Q", data, pos)[0]
    pos += 8
    cameras = {}

    for _ in range(num_cameras):
        if pos + 24 > data_len:
            break

        camera_id = struct.unpack_from("<I", data, pos)[0]; pos += 4
        model_id = struct.unpack_from("<I", data, pos)[0]; pos += 4
        width = struct.unpack_from("<Q", data, pos)[0]; pos += 8
        height = struct.unpack_from("<Q", data, pos)[0]; pos += 8
        num_params = CAMERA_MODEL_PARAM_COUNTS.get(model_id)
        if num_params is None or pos + num_params * 8 > data_len:
            break

        params = list(struct.unpack_from("<" + "d" * num_params, data, pos))
        pos += num_params * 8
        cameras[camera_id] = {
            "id": camera_id,
            "modelId": model_id,
            "width": int(width),
            "height": int(height),
            "params": params,
        }

    return cameras


def camera_intrinsics(camera):
    params = camera["params"]
    model_id = camera["modelId"]
    width = camera["width"]
    height = camera["height"]

    if model_id == 1 and len(params) >= 4:  # PINHOLE: fx, fy, cx, cy
        return params[0], params[1], params[2], params[3]
    if model_id in (0, 2, 3, 7, 8, 9) and len(params) >= 3:
        return params[0], params[0], params[1], params[2]
    if len(params) >= 4:
        return params[0], params[1], params[2], params[3]

    focal = max(width, height)
    return focal, focal, width * 0.5, height * 0.5


def read_null_terminated_string(data: bytes, pos: int):
    end = data.find(b"\0", pos)
    if end < 0:
        return "", len(data)
    return data[pos:end].decode("utf-8", errors="replace"), end + 1


def parse_camera_poses(cameras_data: bytes, images_data: bytes):
    if cameras_data is None or images_data is None or len(images_data) < 8:
        return []

    cameras = parse_cameras_bin(cameras_data)
    data_len = len(images_data)
    pos = 0
    num_images = struct.unpack_from("<Q", images_data, pos)[0]
    pos += 8
    poses = []

    for _ in range(num_images):
        if pos + 64 > data_len:
            break

        image_id = struct.unpack_from("<I", images_data, pos)[0]; pos += 4
        qvec = struct.unpack_from("<dddd", images_data, pos); pos += 32
        tvec = struct.unpack_from("<ddd", images_data, pos); pos += 24
        camera_id = struct.unpack_from("<I", images_data, pos)[0]; pos += 4
        image_name, pos = read_null_terminated_string(images_data, pos)

        if pos + 8 > data_len:
            break
        num_points2d = struct.unpack_from("<Q", images_data, pos)[0]
        pos += 8 + num_points2d * 24
        if pos > data_len:
            break

        camera = cameras.get(camera_id)
        if camera is None:
            continue

        rotation = qvec_to_rotmat(qvec)
        center = mat_transpose_vec_mul(rotation, (-tvec[0], -tvec[1], -tvec[2]))
        fx, fy, cx, cy = camera_intrinsics(camera)
        width = camera["width"]
        height = camera["height"]
        if abs(fx) < 1e-9 or abs(fy) < 1e-9:
            continue

        local_corners = (
            ((0 - cx) / fx, (0 - cy) / fy, 1.0),
            ((width - cx) / fx, (0 - cy) / fy, 1.0),
            ((width - cx) / fx, (height - cy) / fy, 1.0),
            ((0 - cx) / fx, (height - cy) / fy, 1.0),
        )
        world_corners = []
        for local in local_corners:
            offset = mat_transpose_vec_mul(rotation, local)
            world_corners.append((
                center[0] + offset[0],
                center[1] + offset[1],
                center[2] + offset[2],
            ))

        poses.append({
            "id": image_id,
            "cameraId": camera_id,
            "name": image_name,
            "width": width,
            "height": height,
            "center": center,
            "corners": world_corners,
            "numObservations": int(num_points2d),
        })

    return poses


def parse_points3d_bin(data: bytes):
    """
    Parse COLMAP points3D.bin into arrays for Three.js.
    Format per point:
      point3D_id (uint64), x (double), y (double), z (double),
      r (uint8), g (uint8), b (uint8), error (double),
      track_length (uint64), then track_len * (image_id uint32, point2D_idx uint32)
    """
    if data is None:
        return None

    data_len = len(data)
    pos = 0
    total_points = struct.unpack_from("<Q", data, pos)[0]
    pos += 8

    points = []
    colors = []

    for _ in range(total_points):
        if pos + 51 > data_len:  # minimum point size
            break

        pid = struct.unpack_from("<Q", data, pos)[0]; pos += 8
        x = struct.unpack_from("<d", data, pos)[0]; pos += 8
        y = struct.unpack_from("<d", data, pos)[0]; pos += 8
        z = struct.unpack_from("<d", data, pos)[0]; pos += 8
        r = struct.unpack_from("<B", data, pos)[0]; pos += 1
        g = struct.unpack_from("<B", data, pos)[0]; pos += 1
        b = struct.unpack_from("<B", data, pos)[0]; pos += 1
        error = struct.unpack_from("<d", data, pos)[0]; pos += 8

        # Track: (image_id uint32, point2D_idx uint32) = 8 bytes per ref
        track_len = struct.unpack_from("<Q", data, pos)[0]; pos += 8
        pos += track_len * 8

        if pos > data_len:
            break

        points.extend([x, y, z])
        colors.extend([r / 255.0, g / 255.0, b / 255.0])

    import array
    return {
        "points": array.array('f', points).tobytes().hex(),
        "colors": array.array('f', colors).tobytes().hex(),
        "numPoints": len(points) // 3,
        "totalPoints": total_points,
        "truncated": total_points > len(points) // 3,
    }


@router.get("/viewer/{name}/pointcloud")
async def get_pointcloud(name: str):
    """Get point cloud data from COLMAP output for 3D viewing"""
    try:
        config_path = project_dir(PROJECTS_DIR, name) / "config.json"
        if not config_path.exists():
            raise HTTPException(404, f"Project '{name}' not found")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        output_dir = Path(config["outputDir"])
        sparse_dir = output_dir / "sparse" / "0"

        if not sparse_dir.exists():
            return {"success": True, "data": None, "message": "No sparse output yet"}

        points3d_path = sparse_dir / "points3D.bin"
        if not points3d_path.exists():
            return {"success": True, "data": None, "message": "points3D.bin not found"}

        data = read_colmap_bin(points3d_path)
        if data is None:
            return {"success": True, "data": None, "message": "Empty points3D.bin"}

        result = parse_points3d_bin(data)
        if result is None:
            return {"success": True, "data": None, "message": "Failed to parse point cloud"}

        cameras_path = sparse_dir / "cameras.bin"
        images_path = sparse_dir / "images.bin"
        if cameras_path.exists() and images_path.exists():
            result["cameras"] = parse_camera_poses(
                read_colmap_bin(cameras_path),
                read_colmap_bin(images_path),
            )
        else:
            result["cameras"] = []

        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": f"Point cloud parse failed: {e}"}
