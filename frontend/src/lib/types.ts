// ── Material Track ──
export type TrackType = 'panorama_video' | 'standard_photos' | 'aerial_photos'

export interface MaterialTrack {
  id: string
  trackType: TrackType
  label: string
  paths: string[]
}

// ── Pipeline Config ──
export interface PipelineConfig {
  outputDir: string
  secondsPerFrame: number
  maxFrames: number
  metashapeExe?: string
  accuracy?: 'high' | 'medium' | 'low'
  keypointLimit?: number
  maxNumMatches?: number
  enableTransitiveMatching?: boolean
  enableRigRefinement?: boolean
  groundPlane?: boolean
  upAxis?: '+Y' | '-Y' | '+Z' | '-Z' | '+X' | '-X'
}

// ── Pipeline Status ──
export type PipelinePhase = 'idle' | 'extracting' | 'aligning' | 'exporting' | 'done' | 'error'

export interface PipelineProgress {
  phase: PipelinePhase
  overall: number
  stageMessage: string
  extractProgress: number
  alignProgress: number
  exportProgress: number
}

export interface PipelineLog {
  timestamp: string
  level: 'info' | 'warn' | 'error'
  message: string
}

// ── Project ──
export interface ProjectInfo {
  name: string
  outputDir: string
  manifestPath: string | null
  tracks: MaterialTrack[]
  createdAt: string
}

// ── Point Cloud Data (for 3D viewer) ──
export interface PointCloudData {
  points: Float32Array
  colors: Float32Array
  numPoints: number
  totalPoints: number
  truncated: boolean
  cameras: CameraPose[]
}

export interface CameraPose {
  id: number
  cameraId: number
  name: string
  width: number
  height: number
  center: [number, number, number]
  corners: [
    [number, number, number],
    [number, number, number],
    [number, number, number],
    [number, number, number],
  ]
  numObservations: number
}

// ── API Response ──
export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}
