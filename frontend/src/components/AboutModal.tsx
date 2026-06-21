import { X } from 'lucide-react'

interface AboutModalProps { open: boolean; onClose: () => void }

export default function AboutModal({ open, onClose }: AboutModalProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[#1a1d22] border border-white/[0.05] rounded-2xl max-w-sm w-full mx-4"
        style={{ boxShadow: '0 8px 40px rgba(0,0,0,0.4)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 pt-6 pb-4 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-serif text-white/85">PanoFusion</h2>
            <p className="text-sm text-white/25 mt-0.5">v0.2.0</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/[0.04] text-white/15 hover:text-white/45 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 pb-6 space-y-2">
          <p className="text-sm text-white/45">全景重建与补拍融合工作站</p>
          <p className="text-xs text-white/20" style={{ fontFamily: 'Georgia, serif' }}>Created by EdwardJackson</p>
        </div>
      </div>
    </div>
  )
}
