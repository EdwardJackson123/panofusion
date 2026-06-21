const DEFAULT_PORT = 8765
const FALLBACK_PORTS = [8765, 8766, 8767, 8768]
const HEALTH_TTL_MS = 2500

export const EXPECTED_BACKEND_EDITION = 'metashape'
export type BackendHealth = { status?: string; edition?: string }

function readStoredPort(): number | null {
  const saved = sessionStorage.getItem('panofusion-port')
  const port = saved ? Number(saved) : NaN
  return Number.isInteger(port) && port > 0 ? port : null
}

let _port = readStoredPort() ?? DEFAULT_PORT
let _lastHealthAt = 0

export function getBackendPort(): number { return _port }
export function setBackendPort(p: number, edition = EXPECTED_BACKEND_EDITION) {
  _port = p
  sessionStorage.setItem('panofusion-port', String(p))
  sessionStorage.setItem('panofusion-edition', edition)
}

export function getApiBase(): string { return `http://localhost:${_port}/api` }
export function getWsUrl(name: string): string { return `ws://localhost:${_port}/ws/${encodeURIComponent(name)}` }
export function isExpectedBackend(health: BackendHealth): boolean {
  return health.status === 'ok' && health.edition === EXPECTED_BACKEND_EDITION
}

export async function getBackendHealth(port = _port): Promise<BackendHealth> {
  const r = await fetch(`http://localhost:${port}/api/health`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function detectPort(preferred = DEFAULT_PORT): Promise<number | null> {
  const saved = readStoredPort()
  const ports = [...new Set([saved ?? preferred, preferred, ...FALLBACK_PORTS])]
  for (const p of ports) {
    try {
      const health = await getBackendHealth(p)
      if (isExpectedBackend(health)) {
        setBackendPort(p, health.edition)
        _lastHealthAt = Date.now()
        return p
      }
    } catch {}
  }
  sessionStorage.removeItem('panofusion-edition')
  return null
}

export async function ensureBackendPort(): Promise<number> {
  const cachedEdition = sessionStorage.getItem('panofusion-edition')
  if (cachedEdition === EXPECTED_BACKEND_EDITION && Date.now() - _lastHealthAt < HEALTH_TTL_MS) {
    return _port
  }
  const detected = await detectPort()
  if (detected == null) throw new Error('未找到匹配的 Metashape 后端')
  return detected
}
