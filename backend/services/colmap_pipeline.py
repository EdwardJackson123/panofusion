"""
COLMAP Pipeline — feature extraction, matching, sparse reconstruction
"""
import subprocess
import shutil
from pathlib import Path
import json
import os
import struct
import time


DEFAULT_FISHEYE_CAMERA_PARAMS = "1042,1042,1920,1920,0,0,0,0"
MAX_SIFT_FEATURES = 60000
DEFAULT_SIFT_FEATURES = 16000
MATCH_MAX_NUM_MATCHES = 32768


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
    ($_.Name -eq 'colmap.exe' -or $_.Name -eq 'ffmpeg.exe' -or $_.Name -eq 'ffprobe.exe') -and
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

    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))

    for pid in pids:
        add_log("warn", f"终止遗留进程: PID {pid}")
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
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


def _unlink_with_retry(path: Path, output_dir: Path, add_log):
    for attempt in range(3):
        if not path.exists():
            return
        try:
            path.unlink()
            return
        except OSError as exc:
            if not _is_lock_error(exc) or attempt == 2:
                raise
            add_log("warn", f"{path.name} 被占用，正在清理遗留进程后重试...")
            _terminate_stale_processes_for_output(output_dir, add_log)
            time.sleep(0.5)


def _is_child_path(parent: Path, child: Path) -> bool:
    try:
        parent_resolved = parent.resolve()
        child_resolved = child.resolve()
        return child_resolved != parent_resolved and parent_resolved in child_resolved.parents
    except Exception:
        return False


def _cleanup_success_workspace(workspace: Path, output_dir: Path, add_log):
    """Remove COLMAP-only intermediates after the final export is complete."""
    remove_names = (
        "images",
        "_txt_export",
        "sparse_before_ground_align",
        "sparse_raw",
        "sparse_rig_seed",
        "database.db",
        "database.db-shm",
        "database.db-wal",
        "image_list.txt",
        "pano_image_list.txt",
        "photo_image_list.txt",
        "photo_pano_pairs.txt",
        "rig_config.json",
        "panofusion_manifest.json",
    )

    removed = []
    for name in remove_names:
        path = workspace / name
        if not path.exists():
            continue
        if not _is_child_path(workspace, path):
            add_log("warn", f"跳过异常清理路径: {path}")
            continue
        try:
            if path.is_dir():
                _remove_tree_with_retry(path, output_dir, add_log)
            else:
                _unlink_with_retry(path, output_dir, add_log)
            removed.append(name)
        except Exception as exc:
            add_log("warn", f"清理中间文件失败 {name}: {exc}")

    if removed:
        add_log("info", "精简 workspace: 已移除 " + ", ".join(removed))


def _estimate_fisheye_camera_params(image_path: Path, add_log) -> str:
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            width, height = img.size

        if width <= 0 or height <= 0:
            raise ValueError(f"invalid image size {width}x{height}")

        scale = min(width, height) / 3840.0
        focal = max(1.0, 1042.0 * scale)
        cx = width / 2.0
        cy = height / 2.0
        add_log("info", f"鱼眼初始内参: {width}x{height}, f={focal:.1f}, cx={cx:.1f}, cy={cy:.1f}")
        return f"{focal:.3f},{focal:.3f},{cx:.3f},{cy:.3f},0,0,0,0"
    except Exception as exc:
        add_log("warn", f"读取鱼眼图片尺寸失败，使用默认内参: {exc}")
        return DEFAULT_FISHEYE_CAMERA_PARAMS


def run_pipeline(config: dict, update_progress, add_log, is_stopped=None,
                 register_process=None, unregister_process=None):
    output_dir = Path(config["outputDir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    seconds_per_frame = config.get("secondsPerFrame", 1.0)
    max_frames = config.get("maxFrames", 0) or 0
    keypoint_limit = config.get("keypointLimit", DEFAULT_SIFT_FEATURES)
    tracks_config = config.get("tracks", [])
    enable_transitive_matching = bool(config.get("enableTransitiveMatching", False))
    # Keep rig_configurator for left/right fisheye grouping, but disable the
    # slow rig re-mapping/BA pass: it can explode scale on mixed pano+phone data.
    enable_rig_refinement = False
    ground_plane = bool(config.get("groundPlane", True))
    up_axis = config.get("upAxis", "+Y")
    max_num_matches = int(config.get("maxNumMatches", MATCH_MAX_NUM_MATCHES) or MATCH_MAX_NUM_MATCHES)
    max_num_matches = max(4096, min(max_num_matches, MATCH_MAX_NUM_MATCHES))
    colmap_exe = _find_colmap()

    # Feature count is an explicit user parameter. Keep a practical safety
    # clamp so accidental huge values do not make COLMAP crawl or destabilize.
    try:
        max_features = int(keypoint_limit or DEFAULT_SIFT_FEATURES)
    except (TypeError, ValueError):
        max_features = DEFAULT_SIFT_FEATURES
    max_features = max(1000, min(max_features, MAX_SIFT_FEATURES))
    add_log("info", f"COLMAP 参数: features={max_features}, matches={max_num_matches}, transitive={enable_transitive_matching}, rig_refine={enable_rig_refinement}, ground={ground_plane}, up={up_axis}")

    if is_stopped is None:
        is_stopped = lambda: False
    if register_process is None:
        register_process = lambda proc: None
    if unregister_process is None:
        unregister_process = lambda proc: None

    # Clean old output to avoid conflicts. A previous app/backend restart can
    # leave COLMAP alive and holding database.db, so kill only processes whose
    # command line points at this project output directory.
    _terminate_stale_processes_for_output(output_dir, add_log)
    for d in ["workspace", "images", "sparse"]:
        p = output_dir / d
        if p.exists():
            add_log("info", f"清理旧输出: {d}")
            _remove_tree_with_retry(p, output_dir, add_log)

    # ═══ Phase 1: Extract frames ═══
    add_log("info", "开始抽帧...")
    update_progress("extracting", 5, "抽帧中...", 5, 0, 0)

    from .manifest import build_manifest

    pano_videos = []; std_tracks = []; aer_tracks = []
    for t in tracks_config:
        tt = t.get("trackType")
        if tt == "panorama_video": pano_videos.extend(t.get("paths", []))
        elif tt == "standard_photos": std_tracks.append((t.get("label", ""), t.get("paths", [])))
        elif tt == "aerial_photos": aer_tracks.append((t.get("label", ""), t.get("paths", [])))

    def extract_progress(cur, total):
        t = max(total, 1)
        extract_ring = int(100 * cur / t)
        overall = int(25 * cur / t)
        update_progress("extracting", overall, f"抽帧 {cur}/{total}", extract_ring, 0, 0)

    manifest, manifest_path = build_manifest(
        output_dir=output_dir, panorama_videos=pano_videos,
        standard_photo_tracks=std_tracks, aerial_photo_tracks=aer_tracks,
        seconds_per_frame=seconds_per_frame, max_frames=max_frames,
        progress_cb=extract_progress, log_cb=lambda msg: add_log("info", msg),
        is_stopped=is_stopped, register_process=register_process,
        unregister_process=unregister_process,
    )
    total_frames = sum(len(t.get("frames", [])) for t in manifest.get("tracks", []) if t.get("track_type") == "panorama_video")
    total_photos = sum(len(t.get("photos", [])) for t in manifest.get("tracks", []) if t.get("track_type") != "panorama_video")
    add_log("info", f"全景帧: {total_frames}, 照片: {total_photos}")
    update_progress("aligning", 30, f"抽帧完成 ({total_frames} 帧)", 100, 0, 0)

    if is_stopped(): update_progress("idle", 0, "已停止", 0, 0, 0); return

    # ═══ Phase 2: Prepare COLMAP workspace ═══
    workspace = output_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = workspace / "database.db"
    # Always remove stale database
    if db_path.exists():
        _unlink_with_retry(db_path, output_dir, add_log)
    image_dir = workspace / "images"

    # Organize images by physical sensor, not by frame. With
    # single_camera_per_folder this gives one shared left fisheye camera and
    # one shared right fisheye camera per panorama track.
    image_dir.mkdir(exist_ok=True)
    img_list: list[str] = []
    pano_rel_paths: list[str] = []
    photo_rel_paths: list[str] = []
    rig_config: list[dict] = []

    for track in manifest.get("tracks", []):
        if track.get("track_type") == "panorama_video":
            track_id = track["track_id"]
            left_dir = image_dir / track_id / "left"
            right_dir = image_dir / track_id / "right"
            left_dir.mkdir(parents=True, exist_ok=True)
            right_dir.mkdir(parents=True, exist_ok=True)
            rig_config.append({
                "cameras": [
                    {"image_prefix": f"{track_id}/left/", "ref_sensor": True},
                    {"image_prefix": f"{track_id}/right/"},
                ]
            })

            for frame in track.get("frames", []):
                for side in ("left", "right"):
                    src = Path(frame[side])
                    side_dir = left_dir if side == "left" else right_dir
                    dst = side_dir / f"{frame['frame_id']}.jpg"
                    if not dst.exists():
                        shutil.copy2(str(src), str(dst))
                    img_list.append(str(dst))
                    rel = _relative_image_name(dst, image_dir)
                    pano_rel_paths.append(rel)
        else:
            # All photos from one track share one pinhole-ish camera. This is
            # intentionally separate from the fisheye extractor call below.
            track_id = track["track_id"]
            phone_dir = image_dir / track_id / "photos"
            phone_dir.mkdir(parents=True, exist_ok=True)
            for index, photo in enumerate(track.get("photos", []), 1):
                src = Path(photo)
                dst = phone_dir / f"{index:05d}_{src.name}"
                if not dst.exists():
                    shutil.copy2(str(src), str(dst))
                img_list.append(str(dst))
                photo_rel_paths.append(_relative_image_name(dst, image_dir))

    image_list_path = workspace / "image_list.txt"
    image_list_path.write_text("\n".join(pano_rel_paths + photo_rel_paths) + "\n", encoding="utf-8")
    pano_image_list_path = workspace / "pano_image_list.txt"
    photo_image_list_path = workspace / "photo_image_list.txt"
    if pano_rel_paths:
        pano_image_list_path.write_text("\n".join(pano_rel_paths) + "\n", encoding="utf-8")
    if photo_rel_paths:
        photo_image_list_path.write_text("\n".join(photo_rel_paths) + "\n", encoding="utf-8")

    rig_config_path = workspace / "rig_config.json"
    if rig_config:
        rig_config_path.write_text(json.dumps(rig_config, ensure_ascii=False, indent=2), encoding="utf-8")

    add_log("info", f"图像总数: {len(img_list)}")
    add_log("info", f"COLMAP sensor 分组: 鱼眼 {len(pano_rel_paths)} 张, 普通照片 {len(photo_rel_paths)} 张")
    update_progress("aligning", 35, "COLMAP 特征提取...", 100, 5, 0)

    fisheye_camera_params = DEFAULT_FISHEYE_CAMERA_PARAMS
    if pano_rel_paths:
        fisheye_camera_params = _estimate_fisheye_camera_params(image_dir / pano_rel_paths[0], add_log)

    # ═══ Phase 3: COLMAP pipeline ═══

    def run_colmap(args, phase: str = "aligning"):
        cmd = [colmap_exe] + args
        add_log("info", f"  {args[0]}...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        register_process(proc)

        try:
            # Read stdout in a thread so we can poll stop flag
            import threading, queue
            q: queue.Queue = queue.Queue()
            def reader():
                try:
                    for line in proc.stdout:
                        q.put(line)
                except Exception:
                    pass
                q.put(None)  # sentinel
            t = threading.Thread(target=reader, daemon=True)
            t.start()

            while True:
                try:
                    line = q.get(timeout=0.5)
                except queue.Empty:
                    if is_stopped():
                        add_log("warn", "正在终止进程...")
                        _terminate_process_tree(proc)
                        return False
                    continue
                if line is None:  # EOF
                    break
                line = line.rstrip()
                if line.strip():
                    add_log("info", line.strip()[:120])

            t.join(timeout=2)
            if is_stopped():
                return False
            return proc.wait() == 0
        finally:
            unregister_process(proc)

    # Feature extraction. Run fisheye and pinhole-ish images separately so
    # phone/drone tracks are not forced into an OPENCV_FISHEYE camera.
    update_progress("aligning", 38, "特征提取中...", 100, 15, 0)
    if pano_rel_paths:
        if not run_colmap([
            "feature_extractor",
            "--database_path", str(db_path),
            "--image_path", str(image_dir),
            "--image_list_path", str(pano_image_list_path),
            "--ImageReader.camera_model", "OPENCV_FISHEYE",
            "--ImageReader.single_camera", "0",
            "--ImageReader.single_camera_per_folder", "1",
            "--ImageReader.camera_params", fisheye_camera_params,
            "--SiftExtraction.max_num_features", str(max_features),
        ]):
            if is_stopped():
                update_progress("idle", 0, "已停止", 0, 0, 0)
                return
    if photo_rel_paths:
        if not run_colmap([
            "feature_extractor",
            "--database_path", str(db_path),
            "--image_path", str(image_dir),
            "--image_list_path", str(photo_image_list_path),
            "--ImageReader.camera_model", "OPENCV",
            "--ImageReader.single_camera", "0",
            "--ImageReader.single_camera_per_folder", "1",
            "--SiftExtraction.max_num_features", str(max_features),
        ]):
            if is_stopped():
                update_progress("idle", 0, "已停止", 0, 0, 0)
                return

    update_progress("aligning", 55, "特征匹配中...", 100, 40, 0)

    # Sequential matching for video frames. image_list_path above imports
    # left/right frames interleaved, so this still sees temporal neighbors and
    # same-frame fisheye pairs despite the left/right sensor folders.
    if not run_colmap([
        "sequential_matcher",
        "--database_path", str(db_path),
        "--SequentialMatching.overlap", "20",
        "--SequentialMatching.quadratic_overlap", "1",
        "--SequentialMatching.loop_detection", "0",
        "--FeatureMatching.guided_matching", "1",
        "--FeatureMatching.max_num_matches", str(max_num_matches),
    ]):
        if is_stopped():
            update_progress("idle", 0, "已停止", 0, 0, 0)
            return
        raise RuntimeError("COLMAP sequential matching failed")

    # Transitive matching can be very slow on dense video frame sets. Keep it
    # available for experiments, but default to the faster sequential graph.
    if enable_transitive_matching:
        update_progress("aligning", 60, "扩展匹配中...", 100, 45, 0)
        if not run_colmap([
            "transitive_matcher",
            "--database_path", str(db_path),
            "--TransitiveMatching.num_iterations", "1",
            "--FeatureMatching.guided_matching", "1",
            "--FeatureMatching.max_num_matches", str(max_num_matches),
        ]):
            if is_stopped():
                update_progress("idle", 0, "已停止", 0, 0, 0)
                return
            add_log("warn", "Transitive matching failed, continuing...")
    else:
        add_log("info", "跳过 Transitive matching，使用顺序匹配图进入稀疏重建")

    update_progress("aligning", 65, "稀疏重建中...", 100, 50, 0)

    # Step 2: if phone photos exist, do spatial matching using GPS
    if total_photos > 0:
        if not run_colmap([
            "spatial_matcher",
            "--database_path", str(db_path),
            "--SpatialMatching.max_num_neighbors", "5",
        ]):
            if is_stopped():
                update_progress("idle", 0, "已停止", 0, 0, 0)
                return
            add_log("warn", "Spatial matching failed, continuing...")

    if photo_rel_paths and pano_rel_paths:
        pair_list_path = workspace / "photo_pano_pairs.txt"
        pair_count = _write_pair_list(pair_list_path, photo_rel_paths, pano_rel_paths)
        add_log("info", f"普通照片-全景帧匹配对: {pair_count}")
        update_progress("aligning", 68, "普通照片交叉匹配中...", 100, 55, 0)
        if not run_colmap([
            "matches_importer",
            "--database_path", str(db_path),
            "--match_list_path", str(pair_list_path),
            "--match_type", "pairs",
            "--FeatureMatching.guided_matching", "1",
            "--FeatureMatching.max_num_matches", str(max_num_matches),
        ]):
            if is_stopped():
                update_progress("idle", 0, "已停止", 0, 0, 0)
                return
            add_log("warn", "普通照片-全景帧匹配导入失败，尝试全量匹配兜底...")
            if len(img_list) <= 500:
                if not run_colmap([
                    "exhaustive_matcher",
                    "--database_path", str(db_path),
                    "--FeatureMatching.guided_matching", "1",
                    "--FeatureMatching.max_num_matches", str(max_num_matches),
                ]):
                    if is_stopped():
                        update_progress("idle", 0, "已停止", 0, 0, 0)
                        return
                    add_log("warn", "Exhaustive matching failed, continuing with existing matches...")
            else:
                add_log("warn", f"图像数量 {len(img_list)} 太多，跳过全量匹配兜底")
    update_progress("aligning", 70, "稀疏重建中...", 100, 60, 0)

    # First pass: unconstrained shared-sensor reconstruction. This estimates a
    # usable model that rig_configurator can use to infer left/right rig poses.
    raw_sparse_dir = workspace / "sparse_raw"
    raw_sparse_dir.mkdir(exist_ok=True)
    mapper_args = [
        "mapper",
        "--database_path", str(db_path),
        "--image_path", str(image_dir),
        "--output_path", str(raw_sparse_dir),
        "--Mapper.tri_ignore_two_view_tracks", "0",
        "--Mapper.ba_refine_principal_point", "0",
        "--Mapper.ba_refine_focal_length", "1",
        "--Mapper.ba_refine_extra_params", "1",
    ]
    if not run_colmap(mapper_args):
        if is_stopped():
            update_progress("idle", 0, "已停止", 0, 0, 0)
            return

    raw_model_dir = _select_largest_model(raw_sparse_dir)
    if raw_model_dir is None:
        raise RuntimeError("COLMAP failed to create any sparse model")

    final_model_dir = raw_model_dir
    rig_configured = False

    if rig_config:
        update_progress("aligning", 76, "配置双鱼眼 Rig...", 100, 70, 0)
        rig_seed_dir = workspace / "sparse_rig_seed"
        rig_seed_dir.mkdir(exist_ok=True)
        rig_config_ok = run_colmap([
            "rig_configurator",
            "--database_path", str(db_path),
            "--rig_config_path", str(rig_config_path),
            "--input_path", str(raw_model_dir),
            "--output_path", str(rig_seed_dir),
        ])
        if is_stopped():
            update_progress("idle", 0, "已停止", 0, 0, 0)
            return
        if rig_config_ok:
            rig_configured = True
            final_model_dir = rig_seed_dir
            add_log("info", "使用已配置 Rig 的稀疏模型，跳过二次 Rig 优化")
        else:
            add_log("warn", "Rig configuration failed, using shared-sensor model")

    if is_stopped():
        update_progress("idle", 0, "已停止", 0, 0, 0)
        return

    registered_names = _read_image_names(Path(final_model_dir) / "images.bin")
    registered_photo_images = sum(1 for name in registered_names if _is_photo_image_name(name))
    registered_pano_images = len(registered_names) - registered_photo_images
    if photo_rel_paths:
        if registered_photo_images == 0:
            add_log("warn", f"普通照片未注册: 0/{len(photo_rel_paths)}，请检查照片与全景帧重叠或提高匹配设置")
        else:
            add_log("info", f"普通照片注册: {registered_photo_images}/{len(photo_rel_paths)}")

    update_progress("aligning", 88, "模型导出中...", 100, 96, 0)

    # Export to standard COLMAP format
    export_dir = output_dir / "sparse" / "0"
    export_dir.mkdir(parents=True, exist_ok=True)

    model_dir = final_model_dir
    add_log("info", f"Found model in {model_dir}")

    # Copy model files
    for f in model_dir.iterdir():
        if is_stopped():
            update_progress("idle", 0, "已停止", 0, 0, 0)
            return
        if f.is_file():
            shutil.copy2(str(f), str(export_dir / f.name))

    # Cubemap export for fisheye images
    update_progress("exporting", 93, "Cubemap 渲染...", 100, 100, 5)
    export_stats = {}
    try:
        from .colmap_export import export_cubemap_colmap
        # Clear the raw image export and re-export with cubemap
        images_out = output_dir / "images"
        if images_out.exists():
            _remove_tree_with_retry(images_out, output_dir, add_log)
        images_out.mkdir(exist_ok=True)
        # Re-create sparse/0 for standard format
        cubemap_sparse = output_dir / "sparse" / "0"
        if cubemap_sparse.exists():
            _remove_tree_with_retry(cubemap_sparse, output_dir, add_log)
        cubemap_sparse.mkdir(parents=True, exist_ok=True)
        export_stats = export_cubemap_colmap(
            str(model_dir), str(image_dir), str(output_dir),
            face_size=None, add_log=add_log,
        )
        if photo_rel_paths and not export_stats.get("frame_images", 0):
            add_log("warn", "最终导出中没有普通照片 frame 图，普通照片可能未成功注册")
    except Exception as e:
        add_log("warn", f"Cubemap export failed ({e}), falling back to raw images")
        # Fallback: copy raw COLMAP output
        for f in model_dir.iterdir():
            if f.is_file():
                shutil.copy2(str(f), str(export_dir / f.name))
        images_out = output_dir / "images"
        images_out.mkdir(exist_ok=True)
        for img in img_list:
            src = Path(img)
            dst = images_out / src.relative_to(image_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(str(src), str(dst))
        export_stats = {
            "mode": "raw_fallback",
            "output_images": len(img_list),
            "output_cameras": _read_bin_count(export_dir / "cameras.bin"),
            "output_points3D": _read_bin_count(export_dir / "points3D.bin"),
            "cubemap_images": 0,
            "frame_images": len(photo_rel_paths),
        }

    ground_alignment = {"enabled": ground_plane, "applied": False, "up_axis": up_axis}
    if is_stopped():
        update_progress("idle", 0, "已停止", 0, 0, 0)
        return

    if ground_plane:
        update_progress("exporting", 98, "地面对齐...", 100, 100, 92)
        try:
            from .colmap_ground_align import apply_ground_alignment
            ground_alignment = apply_ground_alignment(
                output_dir / "sparse" / "0",
                up_axis=up_axis,
                add_log=add_log,
                force=True,
                backup_dir=workspace / "sparse_before_ground_align",
            )
        except Exception as exc:
            add_log("warn", f"地面对齐失败，保留原始 COLMAP 姿态: {exc}")
            ground_alignment = {
                "enabled": True,
                "applied": False,
                "up_axis": up_axis,
                "error": str(exc),
            }
    else:
        add_log("info", "跳过地面对齐，保留 COLMAP 原始姿态")

    update_progress("exporting", 99, "写入对齐报告...", 100, 100, 98)

    # Write summary
    _write_summary(
        output_dir, workspace, db_path, len(img_list), model_dir,
        rig_config, rig_configured,
        expected_photo_images=len(photo_rel_paths),
        registered_photo_images=registered_photo_images,
        registered_pano_images=registered_pano_images,
        export_stats=export_stats,
        ground_alignment=ground_alignment,
    )

    _cleanup_success_workspace(workspace, output_dir, add_log)

    update_progress("done", 100, "处理完成", 100, 100, 100)
    add_log("info", "管线完成")


def _find_colmap():
    from config import find_colmap_exe
    return find_colmap_exe()


def _relative_image_name(path: Path, image_root: Path) -> str:
    return path.relative_to(image_root).as_posix()


def _write_pair_list(path: Path, left_names: list[str], right_names: list[str]) -> int:
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for left in left_names:
            for right in right_names:
                if left == right:
                    continue
                handle.write(f"{left} {right}\n")
                count += 1
    return count


def _is_photo_image_name(name: str) -> bool:
    return "/photos/" in name.replace("\\", "/").lower()


def _read_bin_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size < 8:
        return 0
    with open(path, "rb") as handle:
        return struct.unpack("<Q", handle.read(8))[0]


def _read_image_names(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size < 8:
        return []
    names: list[str] = []
    with open(path, "rb") as handle:
        count = struct.unpack("<Q", handle.read(8))[0]
        for _ in range(count):
            handle.seek(4 + 32 + 24 + 4, 1)
            name_bytes = bytearray()
            while True:
                ch = handle.read(1)
                if not ch or ch == b"\0":
                    break
                name_bytes.extend(ch)
            names.append(name_bytes.decode("utf-8", errors="replace"))
            point_count = struct.unpack("<Q", handle.read(8))[0]
            handle.seek(point_count * 24, 1)
    return names


def _model_score(model_dir: Path):
    return (
        _read_bin_count(model_dir / "images.bin"),
        _read_bin_count(model_dir / "points3D.bin"),
        (model_dir / "points3D.bin").stat().st_size if (model_dir / "points3D.bin").exists() else 0,
    )


def _select_largest_model(sparse_dir: Path):
    model_dirs = [path for path in sparse_dir.iterdir() if path.is_dir()]
    if not model_dirs:
        return None
    return max(model_dirs, key=_model_score)


def _write_summary(output_dir, workspace, db_path, image_count, model_dir=None,
                   rig_config=None, rig_configured=False,
                   expected_photo_images=0, registered_photo_images=0,
                   registered_pano_images=0, export_stats=None,
                   ground_alignment=None):
    export_dir = Path(output_dir) / "sparse" / "0"
    summary = {
        "workflow": "panofusion-colmap",
        "output_dir": str(output_dir),
        "workspace": str(workspace),
        "workspace_compacted_after_success": True,
        "database": str(db_path),
        "input_images": image_count,
        "expected_photo_images": expected_photo_images,
        "model": str(export_dir),
        "intermediate_model": str(model_dir) if model_dir else None,
        "registered_images": _read_bin_count(Path(model_dir) / "images.bin") if model_dir else 0,
        "registered_pano_images": registered_pano_images,
        "registered_photo_images": registered_photo_images,
        "points3D": _read_bin_count(Path(model_dir) / "points3D.bin") if model_dir else 0,
        "exported_images": _read_bin_count(export_dir / "images.bin"),
        "exported_cameras": _read_bin_count(export_dir / "cameras.bin"),
        "exported_points3D": _read_bin_count(export_dir / "points3D.bin"),
        "export": export_stats or {},
        "ground_alignment": ground_alignment or {},
        "rig_configured": rig_configured,
        "rigs": rig_config or [],
    }
    (workspace / "alignment_summary.txt").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
