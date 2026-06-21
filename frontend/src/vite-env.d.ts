/// <reference types="vite/client" />

interface ElectronAPI {
  selectDirectory: () => Promise<string | null>
  selectFiles: (filters?: { name: string; extensions: string[] }[]) => Promise<string[]>
  getBackendUrl: () => Promise<string>
  onBackendLog: (callback: (msg: string) => void) => void
  removeBackendLogListener: () => void
  minimize: () => void
  maximize: () => void
  close: () => void
}

interface Window {
  electronAPI?: ElectronAPI
}
