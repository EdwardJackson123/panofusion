import type { ApiResponse, PipelineConfig, PipelineProgress, PipelineLog, ProjectInfo, PointCloudData } from './types'
import { detectPort, ensureBackendPort, getApiBase, getWsUrl } from './port'

// Health check returns edition, also lets us discover the actual port
export async function detectBackend(): Promise<string | null> {
  const port = await detectPort()
  return port == null ? null : String(port)
}

export { getApiBase, getWsUrl }

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  await ensureBackendPort()
  const res = await fetch(`${getApiBase()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    const detail = typeof body.detail === 'string' ? body.detail : undefined
    throw new Error(body.error || detail || `HTTP ${res.status}`)
  }
  return res.json()
}

/** Decode hex-encoded binary from the backend into a Float32Array */
export function hexToFloat32Array(hex: string): Float32Array {
  const bytes = new Uint8Array(hex.length / 2)
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16)
  }
  return new Float32Array(bytes.buffer)
}

/** API response for point cloud includes hex-encoded binary */
interface PointCloudResponse {
  points: string  // hex
  colors: string  // hex
  numPoints: number
  totalPoints?: number
  truncated?: boolean
  cameras?: PointCloudData['cameras']
}

// ── Projects ──
export const api = {
  // Project management
  getProjects: () => request<ApiResponse<ProjectInfo[]>>('/projects'),

  createProject: (config: PipelineConfig & { tracks: { trackType: string; label: string; paths: string[] }[] }) =>
    request<ApiResponse<ProjectInfo>>('/projects', { method: 'POST', body: JSON.stringify(config) }),

  // Pipeline control
  startPipeline: (projectName: string) =>
    request<ApiResponse<null>>(`/pipeline/${encodeURIComponent(projectName)}/start`, { method: 'POST' }),

  stopPipeline: (projectName: string) =>
    request<ApiResponse<null>>(`/pipeline/${encodeURIComponent(projectName)}/stop`, { method: 'POST' }),

  resetPipeline: (projectName: string) =>
    request<ApiResponse<null>>(`/pipeline/${encodeURIComponent(projectName)}/reset`, { method: 'POST' }),

  getProgress: (projectName: string) =>
    request<ApiResponse<PipelineProgress>>(`/pipeline/${encodeURIComponent(projectName)}/progress`),

  getLogs: (projectName: string) =>
    request<ApiResponse<PipelineLog[]>>(`/pipeline/${encodeURIComponent(projectName)}/logs`),

  // Point cloud viewer (with hex decoding)
  getPointCloud: async (projectName: string): Promise<ApiResponse<PointCloudData>> => {
    const raw = await request<ApiResponse<PointCloudResponse>>(`/viewer/${encodeURIComponent(projectName)}/pointcloud`)
    if (!raw.success) return { success: false, error: raw.error || '点云加载失败' }
    if (!raw.data) return { success: true }
    return {
      success: true,
      data: {
        points: hexToFloat32Array(raw.data.points),
        colors: hexToFloat32Array(raw.data.colors),
        numPoints: raw.data.numPoints,
        totalPoints: raw.data.totalPoints ?? raw.data.numPoints,
        truncated: raw.data.truncated ?? false,
        cameras: raw.data.cameras ?? [],
      },
    }
  },
}
