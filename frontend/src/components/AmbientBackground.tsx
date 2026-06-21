import { useEffect, useRef } from 'react'

interface Particle {
  x: number; y: number; z: number
  vx: number; vy: number
  size: number; opacity: number
  hue: number
}

interface ClickPulse {
  x: number
  y: number
  startedAt: number
  seed: number
}

const COUNT = 150
const MOUSE_RADIUS = 220
const MOUSE_FORCE = 0.012
const CLICK_RADIUS = 115
const CLICK_FORCE = 0.82
const CLICK_LIFETIME = 620
const RIPPLE_SEGMENTS = 96

// Smooth ease-out cubic — fast near, gentle far
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

function seededUnit(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453
  return x - Math.floor(x)
}

function ringPoint(
  x: number,
  y: number,
  radius: number,
  angle: number,
  seed: number,
  wobble: number,
  phase: number,
) {
  const r =
    radius +
    Math.sin(angle * 4 + seed + phase * 1.35) * wobble * 0.46 +
    Math.sin(angle * 8 + seed * 1.7 - phase * 1.9) * wobble * 0.36 +
    Math.sin(angle * 15 + seed * 0.73 + phase * 2.45) * wobble * 0.18
  return {
    x: x + Math.cos(angle) * r,
    y: y + Math.sin(angle) * r,
  }
}

function drawRippleRing(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  alpha: number,
  seed: number,
  width: number,
  phase: number,
) {
  if (radius <= 4 || alpha <= 0.002) return

  const wobble = Math.min(22, Math.max(7, radius * 0.105))
  ctx.beginPath()
  for (let i = 0; i <= RIPPLE_SEGMENTS; i++) {
    const angle = (i / RIPPLE_SEGMENTS) * Math.PI * 2
    const point = ringPoint(x, y, radius, angle, seed, wobble, phase)
    if (i === 0) ctx.moveTo(point.x, point.y)
    else ctx.lineTo(point.x, point.y)
  }
  ctx.closePath()
  ctx.strokeStyle = `rgba(236,176,126,${alpha})`
  ctx.lineWidth = width
  ctx.stroke()

  for (let arc = 0; arc < 4; arc++) {
    const start = seededUnit(seed + arc * 9.37) * Math.PI * 2
    const length = (0.18 + seededUnit(seed + arc * 3.91) * 0.18) * Math.PI
    ctx.beginPath()
    const steps = 14
    for (let i = 0; i <= steps; i++) {
      const angle = start + (i / steps) * length
      const point = ringPoint(x, y, radius, angle, seed + arc, wobble * 1.12, phase + arc * 0.4)
      if (i === 0) ctx.moveTo(point.x, point.y)
      else ctx.lineTo(point.x, point.y)
    }
    ctx.strokeStyle = `rgba(255,218,176,${alpha * (0.3 + seededUnit(seed + arc) * 0.28)})`
    ctx.lineWidth = width * 0.48
    ctx.stroke()
  }
}

export default function AmbientBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef({ x: -1000, y: -1000, active: false, tx: -1000, ty: -1000 })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animId: number
    let w = 0, h = 0
    let particles: Particle[] = []
    let pulses: ClickPulse[] = []

    const resize = () => {
      w = canvas.width = window.innerWidth
      h = canvas.height = window.innerHeight
    }

    const create = () => {
      particles = Array.from({ length: COUNT }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        z: Math.random() * 3 + 0.3,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        size: Math.random() * 2.2 + 0.6,
        opacity: Math.random() * 0.5 + 0.08,
        hue: Math.random() * 22 + 8,
      }))
    }

    const isInsideWindow = (x: number, y: number) => x >= 0 && y >= 0 && x <= window.innerWidth && y <= window.innerHeight

    const deactivateMouse = () => {
      const mouse = mouseRef.current
      mouse.active = false
      mouse.x = -1000
      mouse.y = -1000
      mouse.tx = -1000
      mouse.ty = -1000
    }

    const draw = (time: number) => {
      ctx.clearRect(0, 0, w, h)
      pulses = pulses.filter(pulse => time - pulse.startedAt < CLICK_LIFETIME)

      // Smooth mouse position (lerp toward actual)
      const m = mouseRef.current
      if (m.active) {
        m.tx += (m.x - m.tx) * 0.08
        m.ty += (m.y - m.ty) * 0.08
      }
      const mx = m.tx, my = m.ty, mActive = m.active

      // Ambient mouse glow — very soft
      if (mActive) {
        const g = ctx.createRadialGradient(mx, my, 0, mx, my, MOUSE_RADIUS)
        g.addColorStop(0, 'rgba(200,120,90,0.02)')
        g.addColorStop(0.5, 'rgba(180,100,70,0.005)')
        g.addColorStop(1, 'transparent')
        ctx.fillStyle = g; ctx.beginPath()
        ctx.arc(mx, my, MOUSE_RADIUS, 0, Math.PI * 2); ctx.fill()
      }

      // Click ripple: one uneven wave ring, not a stack of concentric circles.
      for (const pulse of pulses) {
        const age = Math.max(0, Math.min(1, (time - pulse.startedAt) / CLICK_LIFETIME))
        const alpha = Math.pow(1 - age, 1.75)

        const wash = ctx.createRadialGradient(pulse.x, pulse.y, 0, pulse.x, pulse.y, CLICK_RADIUS * 0.55)
        wash.addColorStop(0, `rgba(224,144,96,${0.022 * alpha})`)
        wash.addColorStop(0.28, `rgba(202,112,78,${0.01 * alpha})`)
        wash.addColorStop(1, 'transparent')
        ctx.fillStyle = wash
        ctx.beginPath()
        ctx.arc(pulse.x, pulse.y, CLICK_RADIUS * 0.55, 0, Math.PI * 2)
        ctx.fill()

        const radius = easeOutCubic(age) * CLICK_RADIUS
        const phase = age * Math.PI * 5.6 + Math.sin(age * Math.PI) * 1.4
        drawRippleRing(ctx, pulse.x, pulse.y, radius, alpha * 0.32, pulse.seed, 1.08, phase)
      }

      for (const p of particles) {
        const speed = 1 / p.z

        // ── Mouse force ──
        let proximity = 0
        let clickGlow = 0
        if (mActive) {
          const dx = mx - p.x, dy = my - p.y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < MOUSE_RADIUS && dist > 0.5) {
            const raw = 1 - dist / MOUSE_RADIUS
            proximity = easeOutCubic(raw)
            const force = raw * MOUSE_FORCE
            // Gentle spiral toward mouse
            p.vx += (dx / dist) * force * 0.5 - (dy / dist) * force * 0.25
            p.vy += (dy / dist) * force * 0.5 + (dx / dist) * force * 0.25
            p.vx *= 0.985; p.vy *= 0.985
          }
        }

        for (const pulse of pulses) {
          const age = Math.max(0, Math.min(1, (time - pulse.startedAt) / CLICK_LIFETIME))
          const dx = p.x - pulse.x
          const dy = p.y - pulse.y
          const dist = Math.hypot(dx, dy)
          const waveRadius = easeOutCubic(age) * CLICK_RADIUS
          const band = 70 + p.z * 12
          const wave = Math.max(0, 1 - Math.abs(dist - waveRadius) / band) * Math.pow(1 - age, 1.15)
          clickGlow = Math.max(clickGlow, wave)
        }

        p.x += p.vx * speed
        p.y += p.vy * speed

        // Clamp velocity
        const vMag = Math.hypot(p.vx, p.vy)
        if (vMag > 1.25) { const s = 1.25 / vMag; p.vx *= s; p.vy *= s }

        // Wrap
        if (p.x < -30) p.x = w + 30; if (p.x > w + 30) p.x = -30
        if (p.y < -30) p.y = h + 30; if (p.y > h + 30) p.y = -30

        // ── Proximity-modulated glow ──
        const pulse = 0.7 + 0.3 * Math.sin(time * 0.001 + p.x * 0.007)
        const baseAlpha = p.opacity * pulse
        // Proximity subtly warms the glow — restrained to avoid glare
        const proxAlpha = baseAlpha + proximity * 0.15 + clickGlow * 0.24
        const proxLightness = 50 + proximity * 12 + clickGlow * 16
        const proxSaturation = 60 - proximity * 8 + clickGlow * 8
        const glowR = p.size * (5 + proximity * 2 + clickGlow * 5)

        const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowR)
        glow.addColorStop(0, `hsla(${p.hue}, ${proxSaturation}%, ${proxLightness}%, ${Math.min(1, proxAlpha * 0.4)})`)
        glow.addColorStop(0.25, `hsla(${p.hue}, ${proxSaturation - 3}%, ${proxLightness - 3}%, ${Math.min(1, proxAlpha * 0.12)})`)
        glow.addColorStop(1, 'transparent')
        ctx.fillStyle = glow; ctx.beginPath()
        ctx.arc(p.x, p.y, glowR, 0, Math.PI * 2); ctx.fill()

        // Core dot
        const coreSize = p.size * (0.55 + proximity * 0.2 + clickGlow * 0.42)
        ctx.fillStyle = `hsla(${p.hue}, ${proxSaturation - 15}%, ${proxLightness + 8}%, ${Math.min(1, proxAlpha)})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, coreSize, 0, Math.PI * 2); ctx.fill()
      }

      // ── Sparse connections near mouse ──
      if (mActive) {
        for (let i = 0; i < particles.length; i++) {
          for (let j = i + 1; j < particles.length; j++) {
            const dx = particles[i].x - particles[j].x
            const dy = particles[i].y - particles[j].y
            const dist = Math.hypot(dx, dy)
            const midX = (particles[i].x + particles[j].x) / 2
            const midY = (particles[i].y + particles[j].y) / 2
            const toMouse = Math.hypot(midX - mx, midY - my)
            if (dist < 120 && toMouse < MOUSE_RADIUS * 1.5) {
              const a = (1 - dist / 120) * (1 - toMouse / (MOUSE_RADIUS * 1.5)) * 0.1
              ctx.strokeStyle = `rgba(210,150,110,${a})`
              ctx.lineWidth = 0.4
              ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y)
              ctx.lineTo(particles[j].x, particles[j].y); ctx.stroke()
            }
          }
        }
      }

      // ── Grain ──
      ctx.fillStyle = 'rgba(0,0,0,0.012)'
      for (let i = 0; i < 30; i++) ctx.fillRect(Math.random() * w, Math.random() * h, 1, 1)
    }

    const animate = (t: number) => { animId = requestAnimationFrame(animate); draw(t) }

    const onMouse = (e: MouseEvent) => {
      if (!isInsideWindow(e.clientX, e.clientY) || document.hidden) {
        deactivateMouse()
        return
      }
      const mouse = mouseRef.current
      if (!mouse.active) {
        mouse.tx = e.clientX
        mouse.ty = e.clientY
      }
      mouse.x = e.clientX
      mouse.y = e.clientY
      mouse.active = true
    }
    const onClick = (e: MouseEvent) => {
      if (!isInsideWindow(e.clientX, e.clientY) || document.hidden) return
      const now = performance.now()
      mouseRef.current.x = e.clientX
      mouseRef.current.y = e.clientY
      mouseRef.current.tx = e.clientX
      mouseRef.current.ty = e.clientY
      mouseRef.current.active = true
      pulses.push({
        x: e.clientX,
        y: e.clientY,
        startedAt: now,
        seed: now * 0.013 + e.clientX * 0.17 + e.clientY * 0.11,
      })
      if (pulses.length > 5) pulses = pulses.slice(-5)

      for (const p of particles) {
        const dx = p.x - e.clientX
        const dy = p.y - e.clientY
        const dist = Math.hypot(dx, dy)
        if (dist <= 1 || dist > CLICK_RADIUS) continue

        const raw = 1 - dist / CLICK_RADIUS
        const force = easeOutCubic(raw) * CLICK_FORCE / p.z
        p.vx += (dx / dist) * force + (-dy / dist) * force * 0.12
        p.vy += (dy / dist) * force + (dx / dist) * force * 0.12
      }
    }
    const onPointerOut = (e: PointerEvent) => {
      if (!e.relatedTarget) deactivateMouse()
    }
    const onVisibilityChange = () => {
      if (document.hidden) deactivateMouse()
    }
    const onResize = () => {
      resize()
      create()
      pulses = []
    }

    resize(); create(); animate(0)
    window.addEventListener('resize', onResize)
    window.addEventListener('mousemove', onMouse)
    window.addEventListener('mousedown', onClick)
    window.addEventListener('blur', deactivateMouse)
    window.addEventListener('pointerout', onPointerOut)
    document.addEventListener('mouseleave', deactivateMouse)
    document.addEventListener('pointerleave', deactivateMouse)
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('mousemove', onMouse)
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('blur', deactivateMouse)
      window.removeEventListener('pointerout', onPointerOut)
      document.removeEventListener('mouseleave', deactivateMouse)
      document.removeEventListener('pointerleave', deactivateMouse)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [])

  return <canvas ref={canvasRef} className="fixed inset-0" style={{ zIndex: 0 }} />
}
