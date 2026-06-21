# PanoFusion

全景相机自动重建 + 补拍融合 + Metashape 自动化工作站

基于 [xPano](https://github.com/eXplorerAI-CN/xPano) 思路重构，提供桌面端全景三维重建体验。

## 功能

- **全景视频处理**: 支持 `.osv` / `.insv` Insta360 / DJI 双鱼眼视频自动抽帧
- **多轨混合重建**: 全景视频 + 普通补拍照片 + 航拍照片联合 Metashape 对齐
- **Metashape 自动化**: Station 约束 → 稀疏对齐 → Folder 释放 → 优化 → COLMAP 导出
- **3D 点云预览**: 支持稀疏点云和相机视锥查看
- **实时进度反馈**: 展示管线进度、阶段状态和运行日志

## 快速开始

### 1. 环境要求

- Windows 10/11
- Python 3.10+
- Agisoft Metashape Professional，本仓库不包含 Metashape 程序本体
- ffmpeg (PATH 中可用)
- Node.js 18+ (前端开发)

### 2. 启动后端

```batch
scripts\start-backend.bat
```

后端运行在 `http://localhost:8765`。可通过 `PANOFUSION_METASHAPE` 指向 `metashape.exe`，或把便携版放到 `Metashape/App/Metashape/metashape.exe`。

### 3. 启动前端 (开发模式)

```batch
cd frontend
npm install
npm run dev
```

前端开发服务器运行在 `http://localhost:5173`。

### 4. 启动 Electron (开发模式)

```batch
npm install
npm run dev:electron
```

## 项目结构

```
PanoFusion/
├── electron/            # 桌面端入口
│   ├── main.js          # 窗口和后端进程管理
│   ├── preload.js       # 客户端桥接
│   └── dev-runner.js    # 开发启动器
├── frontend/            # 界面源码
│   ├── src/
│   │   ├── pages/       # ProjectPage, ViewerPage
│   │   ├── components/  # TrackManager, ProgressPanel, LogViewer, etc.
│   │   ├── hooks/       # useWebSocket, usePipeline
│   │   └── lib/         # API client, types, utils
│   └── index.html
├── backend/             # 服务端逻辑
│   ├── routes/          # API 路由
│   ├── services/        # 核心管线服务
│   │   ├── extractor.py # ffmpeg 抽帧
│   │   ├── manifest.py  # 素材清单构建
│   │   ├── pipeline.py  # Metashape 自动化对齐
│   │   └── exporter.py  # COLMAP 导出
│   ├── ws/              # 进度推送
│   └── main.py          # 服务入口
├── Metashape/           # 可选本地依赖占位，不提交 Metashape 程序本体
└── scripts/             # 启动脚本
```

## License

MIT
