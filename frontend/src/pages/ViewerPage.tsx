import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Minimize2 } from 'lucide-react'
import PointCloudViewer from '@/components/PointCloudViewer'
import WindowControls from '@/components/WindowControls'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { PointCloudData } from '@/lib/types'

export default function ViewerPage() {
  const { projectName } = useParams<{ projectName: string }>()
  const navigate = useNavigate()
  const [data, setData] = useState<PointCloudData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const goHome = useCallback(() => navigate('/', { state: { showSetup: true } }), [navigate])

  const loadData = useCallback(async () => {
    if (!projectName) return
    setLoading(true); setError(null)
    try {
      const res = await api.getPointCloud(projectName)
      if (!res.success) {
        throw new Error(res.error || '加载失败')
      }
      if (res.data && res.data.numPoints > 0) {
        setData(res.data)
      } else {
        setError('没有点云数据，请先运行重建管线')
      }
    } catch (err: any) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [projectName])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') fullscreen ? setFullscreen(false) : goHome()
      if (e.key === 'f' && !e.ctrlKey && !e.metaKey) setFullscreen(v => !v)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [fullscreen, goHome])

  return (
    <div className={cn('h-screen bg-near-black flex flex-col', fullscreen && 'fixed inset-0 z-50')}>
      {/* Header */}
      {!fullscreen && (
        <div className="h-12 shrink-0 flex items-center justify-between px-4 border-b border-white/[0.04]" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
          <div className="flex items-center gap-3" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
            <button onClick={goHome} className="p-1.5 rounded-lg hover:bg-white/[0.04] text-white/30 hover:text-white/60 transition-colors">
              <ArrowLeft className="w-4 h-4" />
            </button>
            <span className="text-sm font-medium text-white/50">点云预览</span>
          </div>
          <div className="flex items-center gap-2" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
            <WindowControls />
          </div>
        </div>
      )}

      {/* Viewer area — takes remaining height */}
      <div className="flex-1 relative bg-near-black">
        {fullscreen && (
          <button onClick={() => setFullscreen(false)}
            className="absolute top-3 right-3 z-10 p-1.5 rounded-lg bg-black/40 text-white/40 hover:text-white/70 transition-colors">
            <Minimize2 className="w-4 h-4" />
          </button>
        )}

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center space-y-3">
              <div className="w-8 h-8 border-2 border-terracotta/40 border-t-terracotta rounded-full animate-spin mx-auto" />
              <p className="text-sm text-white/25">加载点云...</p>
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center space-y-3 max-w-xs">
              <p className="text-sm text-red-400/60">{error}</p>
              <button onClick={goHome} className="text-xs text-white/20 hover:text-white/40 transition-colors">返回主界面</button>
            </div>
          </div>
        )}

        {data && !loading && (
          <div className="absolute inset-0">
            <PointCloudViewer
              points={data.points}
              colors={data.colors}
              numPoints={data.numPoints}
              totalPoints={data.totalPoints}
              truncated={data.truncated}
              cameras={data.cameras}
              className="w-full h-full rounded-none border-0"
            />
          </div>
        )}

      </div>
    </div>
  )
}
