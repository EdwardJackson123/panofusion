import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import type { PipelineProgress } from '@/lib/types'
import { Film, Crosshair, Download, Clock } from 'lucide-react'

interface Props { progress: PipelineProgress; running: boolean; startTime: number }

const stages = [
  { key: 'extract' as const, icon: Film, label: '抽帧', color: '#e8a87c' },
  { key: 'align' as const, icon: Crosshair, label: '对齐', color: '#d97757' },
  { key: 'export' as const, icon: Download, label: '导出', color: '#c96442' },
]

function Ring({ value, color, icon: Icon, label, isActive, isDone }: {
  value: number; color: string; icon: typeof Film; label: string; isActive: boolean; isDone: boolean
}) {
  const dotRef = useRef<SVGCircleElement>(null)
  const angleRef = useRef(Math.random() * Math.PI * 2)
  const r = 44
  const circ = 2 * Math.PI * r

  const [smooth, setSmooth] = useState(0)
  const maxSeen = useRef(0)
  useEffect(() => { if (value > maxSeen.current) maxSeen.current = value }, [value])
  useEffect(() => {
    const id = setInterval(() => {
      setSmooth(prev => {
        const t = maxSeen.current
        if (prev >= t - 0.3) return t
        return prev + (t - prev) * 0.05
      })
    }, 60)
    return () => clearInterval(id)
  }, [])
  const offset = circ - (Math.min(100, smooth) / 100) * circ

  useEffect(() => {
    if (!isActive && !isDone) return
    const el = dotRef.current; if (!el) return
    const speed = 0.022
    let id: number
    const loop = () => { id = requestAnimationFrame(loop); angleRef.current += speed; el.setAttribute('cx', String(50 + r * Math.cos(angleRef.current))); el.setAttribute('cy', String(50 + r * Math.sin(angleRef.current))) }
    loop(); return () => cancelAnimationFrame(id)
  }, [isActive, isDone])

  // Color: pending barely visible, active medium, done full
  const ringOpacity = isDone ? 1 : isActive ? 0.7 : 0.15
  const textClass = isDone ? 'text-white/50' : isActive ? 'text-white/50' : 'text-white/8'
  const iconClass = isDone ? 'text-white/80' : isActive ? 'text-white/40' : 'text-white/8'

  const displayColor = isDone || isActive ? color : 'rgba(255,255,255,0.08)'

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-[120px] h-[120px] flex items-center justify-center">
        {isActive && <div className="absolute inset-2 rounded-full" style={{ boxShadow: `0 0 30px ${color}10` }} />}
        <svg className="absolute inset-0 -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r={r} fill="none" stroke="rgba(255,255,255,0.02)" strokeWidth="2" />
        </svg>
        <svg className="absolute inset-0 -rotate-90" viewBox="0 0 100 100" opacity={ringOpacity}>
          <defs>
            <linearGradient id={`g-${label}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={color} stopOpacity="0.4" />
              <stop offset="100%" stopColor={color} stopOpacity="1" />
            </linearGradient>
          </defs>
          <circle cx="50" cy="50" r={r} fill="none" stroke={`url(#g-${label})`} strokeWidth="2" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 0.5s ease-out' }} />
          {(isActive || isDone) && (
            <circle ref={dotRef} cx="50" cy={50 - r} r="2.5" fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }} />
          )}
        </svg>
        <Icon className={cn('w-6 h-6 relative z-10 transition-all duration-700', iconClass)}
          style={{ color: displayColor }} />
      </div>
      <span className={cn('text-sm font-medium tracking-wide uppercase transition-all duration-700', textClass)}>
        {label}
      </span>
    </div>
  )
}

export default function ProgressRings({ progress, running, startTime }: Props) {
  const labels: Record<string, string> = {
    idle: '就绪', extracting: '抽帧中…', aligning: '对齐中…', exporting: '导出中…', done: '完成', error: '出错',
  }
  const isError = progress.phase === 'error'
  const isDone = progress.phase === 'done'
  const isRunning = running && progress.phase !== 'idle' && !isDone && !isError

  // Overall — slow steady tick, never exceeds backend max
  const [smoothOverall, setSmoothOverall] = useState(0)
  const maxOverall = useRef(0)
  useEffect(() => { if (progress.overall > maxOverall.current) maxOverall.current = progress.overall }, [progress.overall])
  useEffect(() => {
    const id = setInterval(() => {
      setSmoothOverall(prev => {
        const t = maxOverall.current
        if (prev >= t) return t
        // Cap max step at 0.3 per tick, even if far from target
        const step = Math.min((t - prev) * 0.04, 0.3)
        return prev + step
      })
    }, 80)
    return () => clearInterval(id)
  }, [])

  // Timer: runs while active, freezes on done/error.
  const [elapsed, setElapsed] = useState(0)
  const frozenRef = useRef(0)
  useEffect(() => {
    if (!startTime) { setElapsed(0); frozenRef.current = 0; return }
    const currentElapsed = Math.max(frozenRef.current, Math.floor((Date.now() - startTime) / 1000))
    if (!isRunning) { frozenRef.current = currentElapsed; setElapsed(currentElapsed); return }
    const tick = () => {
      const next = Math.floor((Date.now() - startTime) / 1000)
      frozenRef.current = next
      setElapsed(next)
    }
    tick()
    const id = setInterval(tick, 250)
    return () => clearInterval(id)
  }, [startTime, isRunning])

  const m = Math.floor(elapsed / 60)
  const s = elapsed % 60
  const timeStr = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`

  const titleColor = isError ? 'text-red-400' : isDone ? 'text-terracotta-light' : 'text-white/80'

  return (
    <div className="space-y-8">
      {startTime > 0 && (
        <div className="text-center space-y-1">
          <p className={cn('text-xs font-mono uppercase tracking-widest transition-colors duration-700', titleColor)}>
            <Clock className="w-3 h-3 inline mr-1.5" />
            {isRunning ? '已运行' : '总耗时'}
          </p>
          <p className="text-5xl font-mono tabular-nums tracking-tight text-white/90">
            {timeStr}
          </p>
        </div>
      )}

      <h3 className={cn('text-center text-2xl font-serif tracking-wide transition-colors duration-700', titleColor)}>
        {labels[progress.phase]}
      </h3>

      <div className="flex justify-center gap-8">
        {stages.map(s => {
          const rawValue = s.key === 'extract' ? progress.extractProgress : s.key === 'align' ? progress.alignProgress : progress.exportProgress
          const active = isRunning && ((s.key === 'extract' && progress.phase === 'extracting') || (s.key === 'align' && progress.phase === 'aligning') || (s.key === 'export' && progress.phase === 'exporting'))
          const done = progress.phase === 'done' || (s.key === 'extract' && ['aligning', 'exporting', 'done'].includes(progress.phase)) || (s.key === 'align' && ['exporting', 'done'].includes(progress.phase))
          const v = done ? 100 : rawValue
          return <Ring key={s.key} value={v} color={s.color} icon={s.icon} label={s.label} isActive={active} isDone={done} />
        })}
      </div>

      <div className="max-w-[280px] mx-auto space-y-1.5">
        <div className="h-px bg-white/[0.04] rounded-full overflow-hidden">
          <div className={cn('h-full rounded-full transition-colors duration-700',
            isError ? 'bg-red-400/60' : 'bg-gradient-to-r from-terracotta-light/60 via-terracotta to-terracotta-dark')}
            style={{ width: `${smoothOverall}%` }} />
        </div>
        <p className={cn('text-center text-sm font-mono tabular-nums transition-colors duration-700', titleColor)}>
          {smoothOverall.toFixed(1)}%
        </p>
      </div>
    </div>
  )
}
