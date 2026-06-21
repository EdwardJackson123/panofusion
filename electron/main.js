const { app, BrowserWindow, ipcMain, dialog } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

let mainWindow = null
let backendProcess = null
const BACKEND_PORT = 8765
let backendUrl = `http://localhost:${BACKEND_PORT}`

// In packaged app, resources are in process.resourcesPath
// In dev mode, they're relative to __dirname
const isPackaged = app.isPackaged
const RESOURCES = isPackaged ? process.resourcesPath : path.join(__dirname, '..')

function getBackendScript() {
  return path.join(RESOURCES, 'backend', 'main.py')
}

function getBackendPython() {
  if (process.env.PANOFUSION_BACKEND_PYTHON) {
    return process.env.PANOFUSION_BACKEND_PYTHON
  }
  if (process.env.PANOFUSION_PYTHON) {
    return process.env.PANOFUSION_PYTHON
  }
  const fs = require('fs')
  const candidates = [
    path.join(RESOURCES, 'python', 'Scripts', 'python.exe'),
    path.join(RESOURCES, 'python', 'python.exe'),
    path.join(RESOURCES, '.venv', 'Scripts', 'python.exe'),
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  return 'python'
}

function startBackend() {
  const pythonExe = getBackendPython()
  const script = getBackendScript()

  console.log(`[PanoFusion] Starting backend: ${pythonExe} ${script}`)

  backendProcess = spawn(pythonExe, ['-u', script], {
    cwd: path.join(RESOURCES, 'backend'),
    env: {
      ...process.env,
      PANOFUSION_PORT: String(BACKEND_PORT),
      PYTHONUNBUFFERED: '1',
      PYTHONNOUSERSITE: '1',
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  })

  backendProcess.stdout.on('data', (data) => {
    const text = data.toString()
    const match = text.match(/Starting backend on (http:\/\/(?:127\.0\.0\.1|localhost):\d+)/)
    if (match) backendUrl = match[1].replace('127.0.0.1', 'localhost')
    console.log(`[backend] ${text.trim()}`)
    if (mainWindow) {
      mainWindow.webContents.send('backend-log', text.trim())
    }
  })

  backendProcess.stderr.on('data', (data) => {
    console.error(`[backend:err] ${data.toString().trim()}`)
  })

  backendProcess.on('close', (code) => {
    console.log(`[PanoFusion] Backend exited with code ${code}`)
    backendProcess = null
  })

  backendProcess.on('error', (err) => {
    console.error(`[PanoFusion] Backend error:`, err)
    dialog.showErrorBox('Backend Error', `Failed to start Python backend:\n${err.message}`)
  })
}

function stopBackend() {
  if (backendProcess) {
    console.log('[PanoFusion] Stopping backend...')
    if (process.platform === 'win32' && backendProcess.pid) {
      const proc = backendProcess
      spawn('taskkill', ['/F', '/T', '/PID', String(proc.pid)], { windowsHide: true })
        .on('close', () => {
          if (backendProcess === proc) backendProcess = null
        })
      return
    }
    backendProcess.kill('SIGTERM')
    setTimeout(() => {
      if (backendProcess) {
        backendProcess.kill('SIGKILL')
        backendProcess = null
      }
    }, 3000)
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: 'PanoFusion',
    backgroundColor: '#0d0c0a',
    icon: path.join(__dirname, '..', 'frontend', 'public', 'icon.ico'),
    frame: false,
    titleBarStyle: 'hidden',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Remove default menu bar
  const { Menu } = require('electron')
  Menu.setApplicationMenu(null)

  // In dev mode, load Vite dev server. In packaged app, load built files from asar.
  if (!app.isPackaged || process.argv.includes('--dev')) {
    mainWindow.loadURL('http://localhost:5173')
    if (!app.isPackaged) mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// ── IPC Handlers ──
ipcMain.handle('window-minimize', () => mainWindow?.minimize())
ipcMain.handle('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize()
  else mainWindow?.maximize()
})
ipcMain.handle('window-close', () => mainWindow?.close())

ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('select-files', async (_event, filters) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: filters || [{ name: 'All Files', extensions: ['*'] }],
  })
  return result.canceled ? [] : result.filePaths
})

ipcMain.handle('get-backend-url', () => backendUrl)

// ── App Lifecycle ──
app.whenReady().then(() => {
  startBackend()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  stopBackend()
})
