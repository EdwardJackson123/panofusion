import { Check, Info, AlertTriangle, XCircle, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Toast } from '@/hooks/useToast'

interface ToastContainerProps {
  toasts: Toast[]
  onRemove: (id: string) => void
}

const icons = { info: Info, success: Check, warn: AlertTriangle, error: XCircle }
const borderColors = {
  info: 'border-white/10',
  success: 'border-terracotta/30',
  warn: 'border-terracotta/30',
  error: 'border-error-crimson/30',
}

export default function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-8 right-8 z-50 flex flex-col gap-2 max-w-md">
      {toasts.map(toast => {
        const Icon = icons[toast.type]
        return (
          <div
            key={toast.id}
            className={cn(
              'flex items-start gap-3 px-4 py-3 rounded-lg border backdrop-blur-xl',
              'bg-near-black/90',
              borderColors[toast.type],
              'animate-in slide-in-from-right-4 fade-in duration-300',
              'shadow-[0_8px_32px_rgba(0,0,0,0.5)]'
            )}
          >
            <Icon className={cn(
              'w-4 h-4 shrink-0 mt-0.5',
              toast.type === 'error' ? 'text-error-crimson' :
              toast.type === 'warn' ? 'text-terracotta' :
              toast.type === 'success' ? 'text-terracotta' : 'text-white/50'
            )} />
            <p className="text-sm font-sans text-white/80 flex-1 break-all leading-relaxed">{toast.message}</p>
            <button
              onClick={(e) => { e.stopPropagation(); onRemove(toast.id) }}
              className="p-1 -mr-1 -mt-0.5 rounded hover:bg-white/10 text-white/30 hover:text-white/70 transition-colors shrink-0"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
