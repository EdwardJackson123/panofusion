export default function WindowControls() {
  return (
    <div className="flex gap-3" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
      <button onClick={() => window.electronAPI?.minimize()} title="最小化"
        className="w-3.5 h-3.5 rounded-full flex items-center justify-center hover:opacity-70 transition-opacity"
        style={{ background: '#e8a87c' }}>
        <svg width="7" height="1.5" viewBox="0 0 7 2"><rect width="7" height="2" rx="1" fill="rgba(0,0,0,0.25)"/></svg>
      </button>
      <button onClick={() => window.electronAPI?.maximize()} title="最大化"
        className="w-3.5 h-3.5 rounded-full flex items-center justify-center hover:opacity-70 transition-opacity"
        style={{ background: '#d97757' }}>
        <svg width="7" height="7" viewBox="0 0 7 7"><rect x="1" y="1" width="5" height="5" rx="0.5" fill="none" stroke="rgba(0,0,0,0.25)" strokeWidth="1.2"/></svg>
      </button>
      <button onClick={() => window.electronAPI?.close()} title="关闭"
        className="w-3.5 h-3.5 rounded-full flex items-center justify-center hover:opacity-70 transition-opacity"
        style={{ background: '#c96442' }}>
        <svg width="6" height="6" viewBox="0 0 6 6"><line x1="1" y1="1" x2="5" y2="5" stroke="rgba(0,0,0,0.25)" strokeWidth="1.2"/><line x1="5" y1="1" x2="1" y2="5" stroke="rgba(0,0,0,0.25)" strokeWidth="1.2"/></svg>
      </button>
    </div>
  )
}
