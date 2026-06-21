# PanoFusion COLMAP

PanoFusion 的 COLMAP 版本，用于调度双鱼眼全景视频、普通照片和 COLMAP 稀疏重建流程。

## 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- ffmpeg / ffprobe，要求在 PATH 中可用，或自行放到项目根目录/`backend/`
- COLMAP，要求在 PATH 中可用，或自行放到 `colmap/bin/colmap.exe`

## 开发启动

```batch
npm install
cd frontend
npm install
cd ..
npm run dev
```

后端默认运行在 `http://localhost:8765`，前端开发服务器默认运行在 `http://localhost:5173`。

## 外部二进制

仓库不提交 `release/`、`node_modules/`、COLMAP 便携包、ffmpeg 二进制和运行输出。需要打包便携版时，把 COLMAP 放到 `colmap/bin/colmap.exe` 后再执行：

```batch
npm run build
```
