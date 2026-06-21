import { useState, useEffect } from 'react'
import { Film, Camera, Box, ChevronRight, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WelcomeOverlayProps { onDismiss: () => void }

const steps = [
  { icon: Film, title: '添加素材', desc: '导入全景视频、补拍照片或航拍照片' },
  { icon: Camera, title: '设置输出', desc: '选择输出目录，其余参数自动配置' },
  { icon: Box, title: '一键重建', desc: '自动抽帧、对齐、导出，完成后可查看 3D 点云' },
]

export default function WelcomeOverlay({ onDismiss }: WelcomeOverlayProps) {
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (!localStorage.getItem('panofusion-welcome-dismissed')) setVisible(true)
  }, [])

  const dismiss = () => {
    setVisible(false); localStorage.setItem('panofusion-welcome-dismissed', '1'); onDismiss()
  }

  if (!visible) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-near-black/70 backdrop-blur-md">
      <div className="bg-near-black border border-white/[0.08] rounded-very shadow-[0_16px_64px_rgba(0,0,0,0.6)] max-w-lg w-full mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 flex items-start justify-between">
          <div>
            <h2 className="text-subhead-sm font-serif text-white/95">欢迎</h2>
          </div>
          <button onClick={dismiss} className="p-1.5 rounded-subtle hover:bg-white/5 text-white/20 hover:text-white/60 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 pb-4 space-y-4">
          {steps.map((step, i) => {
            const Icon = step.icon
            return (
              <div key={i} className="flex gap-4 items-start">
                <div className="w-10 h-10 rounded-comfortable bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0">
                  <Icon className="w-5 h-5 text-white/50" />
                </div>
                <div>
                  <h3 className="text-feature font-serif text-white/80">{i + 1}. {step.title}</h3>
                  <p className="text-caption font-sans text-white/30 mt-0.5">{step.desc}</p>
                </div>
              </div>
            )
          })}
        </div>
        <div className="px-6 pb-6 pt-2 border-t border-white/[0.06] flex items-center justify-between">
          <p className="text-micro font-mono text-white/15">Ctrl+Enter 开始处理</p>
          <button onClick={dismiss} className={cn(
            'inline-flex items-center gap-1.5 px-5 py-2.5 rounded-generous',
            'bg-terracotta text-ivory text-body-sm font-sans',
            'hover:bg-terracotta-light shadow-[0_0_20px_rgba(201,100,66,0.25)] transition-all duration-300'
          )}>
            开始使用 <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
