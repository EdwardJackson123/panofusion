const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  selectFiles: (filters) => ipcRenderer.invoke('select-files', filters),
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  onBackendLog: (callback) => {
    ipcRenderer.on('backend-log', (_event, msg) => callback(msg))
  },
  removeBackendLogListener: () => {
    ipcRenderer.removeAllListeners('backend-log')
  },
  // Window controls
  minimize: () => ipcRenderer.invoke('window-minimize'),
  maximize: () => ipcRenderer.invoke('window-maximize'),
  close: () => ipcRenderer.invoke('window-close'),
})
