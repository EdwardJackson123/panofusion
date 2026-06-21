import { useState, useCallback, useEffect, useRef } from 'react'
import { useWebSocket } from './useWebSocket'
import { api } from '@/lib/api'
import type { PipelineProgress, PipelineLog } from '@/lib/types'

const idleProgress: PipelineProgress = {
  phase: 'idle',
  overall: 0,
  stageMessage: '',
  extractProgress: 0,
  alignProgress: 0,
  exportProgress: 0,
}

const stoppedProgress: PipelineProgress = { ...idleProgress, stageMessage: '已停止' }

const startingProgress: PipelineProgress = {
  phase: 'extracting',
  overall: 0,
  stageMessage: '初始化...',
  extractProgress: 0,
  alignProgress: 0,
  exportProgress: 0,
}

export function usePipeline(projectName: string | null) {
  const [progress, setProgress] = useState<PipelineProgress>(idleProgress)
  const [logs, setLogs] = useState<PipelineLog[]>([])
  const [running, setRunning] = useState(false)
  const { connected, on } = useWebSocket(projectName)
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  useEffect(() => {
    if (!projectName) return
    let cancelled = false
    ;(async () => {
      try {
        const [progRes, logRes] = await Promise.all([
          api.getProgress(projectName),
          api.getLogs(projectName),
        ])
        if (cancelled) return
        if (progRes.data) {
          setProgress(progRes.data)
          setRunning(progRes.data.phase !== 'done' && progRes.data.phase !== 'error' && progRes.data.phase !== 'idle')
        }
        if (logRes.data) setLogs(logRes.data)
      } catch {
        // backend may still be starting
      }
    })()
    return () => { cancelled = true }
  }, [projectName])

  // WebSocket handlers
  useEffect(() => {
    if (!projectName) return
    const unsubs = [
      on('progress', (data: PipelineProgress) => {
        setProgress(data)
        setRunning(data.phase !== 'done' && data.phase !== 'error' && data.phase !== 'idle')
      }),
      on('log', (data: PipelineLog) => {
        setLogs((prev) => [...prev.slice(-500), data])
      }),
    ]
    return () => unsubs.forEach((fn) => fn())
  }, [projectName, on])

  // Poll as fallback when WebSocket isn't connected
  useEffect(() => {
    if (connected || !projectName) return
    pollRef.current = setInterval(async () => {
      try {
        const [progRes, logRes] = await Promise.all([
          api.getProgress(projectName),
          api.getLogs(projectName),
        ])
        if (progRes.data) {
          setProgress(progRes.data)
          setRunning(progRes.data.phase !== 'done' && progRes.data.phase !== 'error' && progRes.data.phase !== 'idle')
        }
        if (logRes.data) setLogs(logRes.data)
      } catch {
        // backend not ready yet
      }
    }, 1000)
    return () => clearInterval(pollRef.current)
  }, [connected, projectName])

  const start = useCallback(async () => {
    if (!projectName) return
    setRunning(true)
    setProgress(startingProgress)
    setLogs([])
    try {
      await api.startPipeline(projectName)
    } catch (err: any) {
      const message = err?.message || '启动失败'
      setRunning(false)
      setProgress({ ...startingProgress, phase: 'error', stageMessage: message })
      setLogs((prev) => [...prev, { timestamp: new Date().toISOString(), level: 'error', message }])
    }
  }, [projectName])

  const stop = useCallback(async () => {
    if (!projectName) return
    const previousProgress = progress
    const wasRunning = running
    setRunning(false)
    setProgress(stoppedProgress)
    setLogs((prev) => [...prev.slice(-500), {
      timestamp: new Date().toISOString(),
      level: 'warn',
      message: '已请求停止重建',
    }])
    try {
      await api.stopPipeline(projectName)
      const progRes = await api.getProgress(projectName).catch(() => null)
      if (progRes?.data) {
        setProgress(progRes.data)
        setRunning(progRes.data.phase !== 'done' && progRes.data.phase !== 'error' && progRes.data.phase !== 'idle')
      }
    } catch (err: any) {
      const message = err?.message || '停止请求发送失败，后端可能仍在运行'
      setLogs((prev) => [...prev.slice(-500), {
        timestamp: new Date().toISOString(),
        level: 'error',
        message,
      }])
      try {
        const progRes = await api.getProgress(projectName)
        if (progRes.data) {
          setProgress(progRes.data)
          setRunning(progRes.data.phase !== 'done' && progRes.data.phase !== 'error' && progRes.data.phase !== 'idle')
          return
        }
      } catch {}
      setProgress({ ...previousProgress, stageMessage: message })
      setRunning(wasRunning)
    }
  }, [projectName, progress, running])

  const reset = useCallback(async () => {
    if (!projectName) return
    setRunning(false)
    setProgress({ ...idleProgress })
    setLogs([])
    try {
      await api.resetPipeline(projectName)
    } catch {
      // Backend may still be starting; keep the local setup screen usable.
    }
  }, [projectName])

  return { progress, logs, running, connected, start, stop, reset }
}
