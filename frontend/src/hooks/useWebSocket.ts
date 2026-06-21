import { useEffect, useRef, useState, useCallback } from 'react'
import { getWsUrl } from '@/lib/port'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type MessageHandler = (data: any) => void

export function useWebSocket(projectName: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const handlersRef = useRef<Map<string, Set<MessageHandler>>>(new Map())
  const [connected, setConnected] = useState(false)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()
  const shouldReconnectRef = useRef(false)

  const connect = useCallback(() => {
    if (!projectName || !shouldReconnectRef.current) return

    const ws = new WebSocket(getWsUrl(projectName))

    ws.onopen = () => {
      setConnected(true)
      wsRef.current = ws
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const handlers = handlersRef.current.get(msg.type)
        if (handlers) {
          handlers.forEach((fn) => fn(msg.data))
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      if (shouldReconnectRef.current) {
        reconnectTimer.current = setTimeout(connect, 2000)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [projectName])

  useEffect(() => {
    shouldReconnectRef.current = true
    connect()
    return () => {
      shouldReconnectRef.current = false
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const on = useCallback((type: string, handler: MessageHandler) => {
    if (!handlersRef.current.has(type)) {
      handlersRef.current.set(type, new Set())
    }
    handlersRef.current.get(type)!.add(handler)
    return () => {
      handlersRef.current.get(type)?.delete(handler)
    }
  }, [])

  return { connected, on }
}
