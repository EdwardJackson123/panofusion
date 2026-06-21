import { useState, useCallback } from 'react'

export interface Toast {
  id: string
  type: 'info' | 'success' | 'warn' | 'error'
  message: string
  duration?: number
}

let _addToast: ((t: Omit<Toast, 'id'>) => void) | null = null

export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const duration = t.duration ?? 4000
    const toast: Toast = { ...t, id, duration }
    setToasts((prev) => [...prev.slice(-4), toast])
    if (duration > 0) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== id))
      }, toast.duration)
    }
    return id
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  // Expose globally for components that can't use hooks
  _addToast = addToast

  return { toasts, addToast, removeToast }
}

// Global toast function for non-React code
export function toast(type: Toast['type'], message: string, duration?: number) {
  _addToast?.({ type, message, duration })
}
