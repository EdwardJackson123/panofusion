import { useState, useCallback, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Play, Square, Box, Info, Plus, Trash2, Film, Camera, Plane, FolderOpen, ChevronDown, ChevronRight, Eye } from 'lucide-react'
import AmbientBackground from '@/components/AmbientBackground'
import WindowControls from '@/components/WindowControls'
import ToastContainer from '@/components/ToastContainer'
import WelcomeOverlay from '@/components/WelcomeOverlay'
import AboutModal from '@/components/AboutModal'
import ProgressRings from '@/components/ProgressRings'
import { usePipeline } from '@/hooks/usePipeline'
import { useToast } from '@/hooks/useToast'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { getApiBase, detectPort, EXPECTED_BACKEND_EDITION } from '@/lib/port'
import type { MaterialTrack, TrackType } from '@/lib/types'

const STORAGE_KEY = 'panofusion-project-state'
function loadState() { try { const r = localStorage.getItem(STORAGE_KEY); if (r) return JSON.parse(r) } catch {} return null }
function saveState(s: object) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)) } catch {} }

const trackDef: Record<TrackType, { icon: typeof Film; label: string }> = {
  panorama_video: { icon: Film, label: '全景视频' },
  standard_photos: { icon: Camera, label: '普通照片' },
  aerial_photos: { icon: Plane, label: '航拍照片' },
}

export default function ProjectPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { toasts, addToast, removeToast } = useToast()
  const init = loadState()

  const [tracks, setTracks] = useState<MaterialTrack[]>(init?.tracks || [])
  const [outputDir, setOutputDir] = useState(init?.outputDir || '')
  const [secondsPerFrame, setSecondsPerFrame] = useState(init?.secondsPerFrame || 1.0)
  const [maxFrames, setMaxFrames] = useState(init?.maxFrames || 0)
  const [projectName] = useState(init?.projectName || 'default')
  const [aboutOpen, setAboutOpen] = useState(false)
  const [backendOnline, setBackendOnline] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [startTime, setStartTime] = useState(0)
  const [accuracy, setAccuracy] = useState<'high' | 'medium' | 'low'>(init?.accuracy || 'high')
  const [keypointLimit, setKeypointLimit] = useState(init?.keypointLimit || 40000)
  const [tiepointLimit, setTiepointLimit] = useState(init?.tiepointLimit || 0)
  const [groundPlane, setGroundPlane] = useState(init?.groundPlane ?? true)
  const [upAxis, setUpAxis] = useState(init?.upAxis || '+Y')

  const { progress, running, start, stop, reset } = usePipeline(projectName)
  const canStart = tracks.length > 0 && outputDir && !running && backendOnline
  const startBlockedMessage = running
    ? ''
    : !backendOnline
      ? '后端未连接，请确认打包目录包含 resources/python，或安装并配置 Python 后端环境。'
      : !outputDir
        ? '请选择输出目录。'
        : tracks.length === 0
          ? '请先添加素材。'
          : ''

  useEffect(() => {
    const state = location.state as { showSetup?: boolean } | null
    if (!state?.showSetup) return
    void reset()
    window.history.replaceState({}, document.title)
  }, [location.state, reset])

  // Track pipeline start time
  useEffect(() => {
    if (running && startTime === 0) setStartTime(Date.now())
    if (!running && progress.phase === 'idle') setStartTime(0)
  }, [running, progress.phase])

  useEffect(() => {
    saveState({
      tracks,
      outputDir,
      secondsPerFrame,
      maxFrames,
      projectName,
      accuracy,
      keypointLimit,
      tiepointLimit,
      groundPlane,
      upAxis,
    })
  }, [tracks, outputDir, secondsPerFrame, maxFrames, projectName, accuracy, keypointLimit, tiepointLimit, groundPlane, upAxis])
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    let notified = false

    const check = async () => {
      try {
        const port = await detectPort()
        if (cancelled) return
        if (port != null) {
          setBackendOnline(true)
          return
        }
        throw new Error('backend edition mismatch or not ready')
      } catch {
        if (cancelled) return
        setBackendOnline(false)
        attempts += 1
        if (attempts >= 4 && !notified) {
          notified = true
          addToast({ type: 'error', message: `未找到 ${EXPECTED_BACKEND_EDITION} 版后端，请确认对应版本已启动` })
        }
        timer = setTimeout(check, 1000)
      }
    }

    check()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [addToast])
  useEffect(() => {
    if (progress.phase === 'error' && progress.stageMessage) addToast({ type: 'error', message: progress.stageMessage, duration: 0 })
  }, [progress.phase, progress.stageMessage])

  const buildProjectConfig = useCallback(() => ({
    name: projectName,
    outputDir,
    secondsPerFrame,
    maxFrames,
    accuracy,
    keypointLimit,
    tiepointLimit,
    groundPlane,
    upAxis,
    tracks: tracks.map(t => ({ trackType: t.trackType, label: t.label, paths: t.paths })),
  }), [projectName, outputDir, secondsPerFrame, maxFrames, accuracy, keypointLimit, tiepointLimit, groundPlane, upAxis, tracks])

  const saveProject = useCallback(async () => {
    const res = await fetch(getApiBase() + '/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildProjectConfig()),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.error || body.detail || '保存项目失败')
    }
  }, [buildProjectConfig])

  const handleStart = useCallback(async () => {
    if (!canStart) return
    try {
      await saveProject()
      await start()
    } catch (err: any) { addToast({ type: 'error', message: err.message, duration: 0 }) }
  }, [canStart, saveProject, start, addToast])

  const handleOpenViewer = useCallback(async () => {
    if (outputDir) {
      try {
        await saveProject()
      } catch (err: any) {
        addToast({ type: 'error', message: err?.message || '保存项目失败', duration: 0 })
        return
      }
    }
    navigate(`/viewer/${projectName}`)
  }, [outputDir, saveProject, navigate, projectName, addToast])

  const handleNewTask = useCallback(async () => {
    await reset()
    setTracks([])
    setOutputDir('')
    setSecondsPerFrame(1.0)
    setMaxFrames(0)
    setStartTime(0)
    setAccuracy('high')
    setKeypointLimit(40000)
    setTiepointLimit(0)
    setGroundPlane(true)
    setUpAxis('+Y')
    setAdvancedOpen(false)
  }, [reset])

  const addTrack = async (type: TrackType) => {
    let paths: string[] = []
    if (type === 'panorama_video') {
      if (window.electronAPI) paths = await window.electronAPI.selectFiles([{ name: '视频', extensions: ['osv', 'insv', 'mp4'] }])
      else { const i = prompt('路径:'); if (i) paths = i.split(';').map(s => s.trim()).filter(Boolean) }
    } else {
      if (window.electronAPI) { const d = await window.electronAPI.selectDirectory(); if (d) paths = [d] }
      else { const i = prompt('路径:'); if (i) paths = [i.trim()] }
    }
    if (!paths.length) return
    setTracks([...tracks, { id: `${type}-${Date.now()}`, trackType: type, label: paths[0].split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') || type, paths }])
  }
  const removeTrack = (id: string) => setTracks(tracks.filter(t => t.id !== id))
  const pickOutput = async () => {
    if (window.electronAPI) { const d = await window.electronAPI.selectDirectory(); if (d) setOutputDir(d) }
    else { const i = prompt('输出目录:'); if (i) setOutputDir(i) }
  }

  useKeyboardShortcuts([
    { key: 'Enter', ctrl: true, handler: handleStart, disabled: !canStart, description: '开始' },
    { key: 'V', ctrl: true, shift: true, handler: () => navigate(`/viewer/${projectName}`), disabled: progress.phase !== 'done', description: '查看器' },
  ])

  return (
    <div className="min-h-screen text-white overflow-hidden" style={{ background: '#0d0c0a' }}>
      <AmbientBackground />
      <ToastContainer toasts={toasts} onRemove={removeToast} />
      <WelcomeOverlay onDismiss={() => {}} />
      <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} />

      {progress.phase === 'idle' ? (
        // ═══ Idle / Setup View ═══
        <div className="relative z-10 flex min-h-screen">
          {/* Sidebar */}
          <aside className="w-72 shrink-0 border-r flex flex-col" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
            <div className="px-7 pt-4 pb-2" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
              <h1 className="text-base font-serif tracking-tight text-white/85" style={{ fontFamily: 'Georgia, serif' }}>PanoFusion</h1>
            </div>
            <div className="px-7 pb-5">
              <p className="text-sm text-white/45" style={{ fontFamily: 'Georgia, serif', fontStyle: 'italic' }}>Panoramic reconstruction</p>
            </div>
            <nav className="flex-1 px-5 py-6 space-y-1">
              <p className="px-2 mb-3 text-xs font-medium uppercase tracking-wider text-white/70">素材</p>
              {Object.entries(trackDef).map(([type, cfg]) => {
                const Icon = cfg.icon
                const count = tracks.filter(t => t.trackType === type).length
                return (
                  <button key={type} onClick={() => addTrack(type as TrackType)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 text-left rounded-md transition-colors duration-150 group"
                    style={{ WebkitAppRegion: 'no-drag', color: 'rgba(255,255,255,0.3)' } as React.CSSProperties}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
                  >
                    <Icon className="w-4 h-4 shrink-0 opacity-60" />
                    <span className="text-sm flex-1">{cfg.label}</span>
                    {count > 0 && <span className="text-xs font-mono opacity-35">{count}</span>}
                    <Plus className="w-3 h-3 opacity-0 group-hover:opacity-30 transition-opacity" />
                  </button>
                )
              })}
            </nav>
            <div className="px-5 py-4 border-t space-y-1" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
              <button onClick={handleOpenViewer}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-white/45 hover:text-white/45 hover:bg-white/[0.02] transition-colors">
                <Eye className="w-3.5 h-3.5" />查看点云
              </button>
              <button onClick={() => setAboutOpen(true)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-white/45 hover:text-white/45 hover:bg-white/[0.02] transition-colors">
                <Info className="w-3.5 h-3.5" />关于
              </button>
            </div>
          </aside>

          {/* Main */}
          <div className="flex-1 flex flex-col">
            <div className="pt-4 pb-2 shrink-0 flex items-center justify-end px-4" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
              <WindowControls />
            </div>
            <div className="flex-1 p-10 flex flex-col">
              <div className="mb-10">
                <label className="text-xs font-medium uppercase tracking-wider text-white/70 mb-3 block">输出目录</label>
                <div className="flex items-center gap-2">
                  <input type="text" value={outputDir} onChange={e => setOutputDir(e.target.value)}
                    placeholder="选择输出位置…"
                    className="flex-1 max-w-md px-0 py-2 text-lg bg-transparent text-white/75 placeholder:text-white/40 focus:outline-none border-b"
                    style={{ borderColor: 'rgba(255,255,255,0.08)' }} />
                  <button onClick={pickOutput}
                    className="px-3 py-1.5 rounded text-xs font-medium transition-colors duration-150"
                    style={{ background: 'rgba(255,255,255,0.03)', color: 'rgba(255,255,255,0.3)' }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; e.currentTarget.style.color = 'rgba(255,255,255,0.3)' }}
                  >
                    <FolderOpen className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="mb-10 flex-1">
                <label className="text-xs font-medium uppercase tracking-wider text-white/70 mb-4 block">已添加的素材 ({tracks.length})</label>
                {tracks.length > 0 ? (
                  <div className="space-y-0.5 max-w-lg">
                    {tracks.map((track, i) => {
                      const cfg = trackDef[track.trackType]
                      const Icon = cfg.icon
                      return (
                        <div key={track.id} className="flex items-center gap-4 px-0 py-2.5 group transition-colors duration-150"
                          style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                          <span className="text-xs font-mono text-white/45 w-5 text-right">{String(i + 1).padStart(2, '0')}</span>
                          <Icon className="w-4 h-4 text-white/40 shrink-0" />
                          <span className="text-sm text-white/70 flex-1 truncate">{track.label}</span>
                          <span className="text-xs text-white/30 font-mono">{cfg.label}</span>
                          <button onClick={() => removeTrack(track.id)}
                            className="p-1 rounded opacity-0 group-hover:opacity-100 text-white/35 hover:text-red-400/40 transition-all">
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-xs font-medium uppercase tracking-wider text-white/70 py-8">请从左侧添加素材</p>
                )}
              </div>

              <div className="max-w-lg">
                <button onClick={() => setAdvancedOpen(!advancedOpen)}
                  className="flex items-center gap-2 text-sm text-white/50 hover:text-white/70 transition-colors mb-4">
                  {advancedOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                  处理参数
                </button>
                {advancedOpen && (
                  <div className="space-y-5 mb-8 animate-in fade-in duration-200">
                    <div className="flex gap-8">
                      <div>
                        <p className="text-xs text-white/50 mb-1.5 uppercase tracking-wider">秒 / 帧</p>
                        <input type="number" value={secondsPerFrame} onChange={e => setSecondsPerFrame(parseFloat(e.target.value) || 1)} min={0.1} step={0.1}
                          className="w-20 px-0 py-1 text-sm font-mono bg-transparent text-white/70 focus:outline-none border-b"
                          style={{ borderColor: 'rgba(255,255,255,0.08)' }} />
                      </div>
                      <div>
                        <p className="text-xs text-white/50 mb-1.5 uppercase tracking-wider">帧数上限</p>
                        <input type="number" value={maxFrames} onChange={e => setMaxFrames(parseInt(e.target.value) || 0)} min={0}
                          className="w-20 px-0 py-1 text-sm font-mono bg-transparent text-white/70 focus:outline-none border-b"
                          style={{ borderColor: 'rgba(255,255,255,0.08)' }} />
                      </div>
                      <div>
                        <p className="text-xs text-white/50 mb-1.5 uppercase tracking-wider">对齐精度</p>
                        <select value={accuracy} onChange={e => setAccuracy(e.target.value as 'high' | 'medium' | 'low')}
                          className="px-0 py-1 text-sm bg-transparent text-white/70 focus:outline-none border-b cursor-pointer"
                          style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
                          <option value="high" className="bg-[#1a1d22]">高</option>
                          <option value="medium" className="bg-[#1a1d22]">中</option>
                          <option value="low" className="bg-[#1a1d22]">低</option>
                        </select>
                      </div>
                      <div>
                        <p className="text-xs text-white/50 mb-1.5 uppercase tracking-wider">关键点</p>
                        <input type="number" value={keypointLimit} onChange={e => setKeypointLimit(parseInt(e.target.value) || 40000)} min={1000} step={1000}
                          className="w-20 px-0 py-1 text-sm font-mono bg-transparent text-white/70 focus:outline-none border-b"
                          style={{ borderColor: 'rgba(255,255,255,0.08)' }} />
                      </div>
                    </div>
                    <div className="flex gap-8 items-end">
                      <div>
                        <p className="text-xs text-white/50 mb-1.5 uppercase tracking-wider">连点上限</p>
                        <input type="number" value={tiepointLimit} onChange={e => setTiepointLimit(parseInt(e.target.value) || 0)} min={0} step={1000}
                          className="w-20 px-0 py-1 text-sm font-mono bg-transparent text-white/70 focus:outline-none border-b"
                          style={{ borderColor: 'rgba(255,255,255,0.08)' }} />
                      </div>
                      <div>
                        <p className="text-xs text-white/50 mb-1.5 uppercase tracking-wider">上轴</p>
                        <select value={upAxis} onChange={e => setUpAxis(e.target.value)}
                          className="px-0 py-1 text-sm bg-transparent text-white/70 focus:outline-none border-b cursor-pointer"
                          style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
                          {['+Y','-Y','+Z','-Z','+X','-X'].map(a => (
                            <option key={a} value={a} className="bg-[#1a1d22]">{a}</option>
                          ))}
                        </select>
                      </div>
                      <div className="flex items-center gap-2 pb-1">
                        <button onClick={() => setGroundPlane(!groundPlane)}
                          className="relative w-8 h-4 rounded-full transition-colors duration-200"
                          style={{ background: groundPlane ? 'rgba(201,100,66,0.5)' : 'rgba(255,255,255,0.08)' }}>
                          <div className="absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all duration-200"
                            style={{ left: groundPlane ? '18px' : '2px' }} />
                        </button>
                        <span className="text-xs text-white/50 uppercase tracking-wider">地平面校正</span>
                      </div>
                    </div>
                  </div>
                )}
                <button onClick={handleStart} disabled={!canStart}
                  className="group relative flex items-center gap-4 px-10 py-5 rounded-2xl text-lg font-medium transition-all duration-300 disabled:opacity-15 disabled:cursor-not-allowed"
                  style={{
                    background: 'linear-gradient(135deg, rgba(201,100,66,0.95), rgba(180,80,50,0.9))',
                    color: '#faf9f5',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.15), 0 4px 16px rgba(201,100,66,0.25), inset 0 1px 0 rgba(255,255,255,0.12)',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}
                  onMouseEnter={e => { if (e.currentTarget.disabled) return; e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.2), 0 8px 24px rgba(201,100,66,0.35), inset 0 1px 0 rgba(255,255,255,0.15)' }}
                  onMouseLeave={e => { if (e.currentTarget.disabled) return; e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.15), 0 4px 16px rgba(201,100,66,0.25), inset 0 1px 0 rgba(255,255,255,0.12)' }}
                >
                  开始重建
                  <span className="flex items-center transition-transform duration-300 group-hover:translate-x-1">
                    <Play className="w-5 h-5" fill="currentColor" />
                  </span>
                </button>
                {startBlockedMessage && (
                  <p className="mt-3 max-w-md text-xs leading-5 text-white/35">
                    {startBlockedMessage}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        // ═══ Progress View ═══
        <div className="relative z-10 min-h-screen flex flex-col">
          <div className="pt-4 pb-2 shrink-0 flex items-center justify-end px-4" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
            <WindowControls />
          </div>
          <div className="flex-1 flex items-center justify-center">
            <div className="max-w-md w-full px-8">
              <ProgressRings progress={progress} running={running} startTime={startTime} />
              {progress.phase === 'error' && progress.stageMessage && (
                <div className="mt-8 p-5 border border-red-400/10" style={{ background: 'rgba(180,50,50,0.04)' }}>
                  <p className="text-sm text-red-400/60">{progress.stageMessage}</p>
                </div>
              )}
              <div className="flex justify-center gap-3 mt-10">
                {running && (
                  <button onClick={stop}
                    className="flex items-center gap-2 px-6 py-3 text-sm transition-colors duration-150"
                    style={{ color: 'rgba(255,255,255,0.3)' }}
                    onMouseEnter={e => e.currentTarget.style.color = 'rgba(255,255,255,0.6)'}
                    onMouseLeave={e => e.currentTarget.style.color = 'rgba(255,255,255,0.3)'}>
                    <Square className="w-3.5 h-3.5" />停止
                  </button>
                )}
                {progress.phase === 'done' && (
                  <button onClick={() => navigate(`/viewer/${projectName}`)}
                    className="flex items-center gap-2 px-6 py-3 text-sm transition-colors duration-150"
                    style={{ color: 'rgba(255,255,255,0.3)' }}
                    onMouseEnter={e => e.currentTarget.style.color = 'rgba(255,255,255,0.6)'}
                    onMouseLeave={e => e.currentTarget.style.color = 'rgba(255,255,255,0.3)'}>
                    <Box className="w-3.5 h-3.5" />查看点云
                  </button>
                )}
                {(progress.phase === 'done' || progress.phase === 'error') && (
                  <button onClick={handleNewTask}
                    className="px-6 py-3 rounded-md text-sm font-medium transition-all duration-200"
                    style={{ background: '#c96442', color: '#faf9f5' }}>
                    新建任务
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
