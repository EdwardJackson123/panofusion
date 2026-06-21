import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { CameraPose } from '@/lib/types'

interface Props {
  points: Float32Array | null
  colors: Float32Array | null
  numPoints: number
  totalPoints?: number
  truncated?: boolean
  cameras?: CameraPose[]
  className?: string
}

interface SavedView {
  position: THREE.Vector3
  target: THREE.Vector3
}

type PoseDisplayMode = 'frustum' | 'hidden'

const clamp01 = (value: number) => Math.min(1, Math.max(0, value))

function formatPointCount(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
}

function makePointTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 48
  canvas.height = 48

  const ctx = canvas.getContext('2d')!
  const glow = ctx.createRadialGradient(24, 24, 0, 24, 24, 24)
  glow.addColorStop(0, 'rgba(255,255,255,0.98)')
  glow.addColorStop(0.46, 'rgba(255,255,255,0.9)')
  glow.addColorStop(0.72, 'rgba(255,255,255,0.28)')
  glow.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, 48, 48)

  const texture = new THREE.CanvasTexture(canvas)
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.generateMipmaps = false
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

function makeAxisLabelSprite(label: string, color: string) {
  const canvas = document.createElement('canvas')
  canvas.width = 160
  canvas.height = 160

  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, 160, 160)
  ctx.fillStyle = 'rgba(8, 12, 15, 0.82)'
  ctx.beginPath()
  ctx.roundRect(38, 38, 84, 84, 24)
  ctx.fill()
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)'
  ctx.lineWidth = 4
  ctx.stroke()
  ctx.fillStyle = color
  ctx.font = '800 64px Inter, system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, 80, 83)

  const texture = new THREE.CanvasTexture(canvas)
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.generateMipmaps = false
  texture.colorSpace = THREE.SRGBColorSpace

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(0.56, 0.56, 0.56)
  return sprite
}

function makeAxis(direction: THREE.Vector3, color: string, label: string) {
  const group = new THREE.Group()
  const axisMaterial = new THREE.MeshBasicMaterial({ color })
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.72, 16), axisMaterial)
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.062, 0.16, 24), axisMaterial)
  const up = new THREE.Vector3(0, 1, 0)
  const q = new THREE.Quaternion().setFromUnitVectors(up, direction.clone().normalize())

  shaft.quaternion.copy(q)
  shaft.position.copy(direction).multiplyScalar(0.36)
  arrow.quaternion.copy(q)
  arrow.position.copy(direction).multiplyScalar(0.8)

  const labelSprite = makeAxisLabelSprite(label, color)
  labelSprite.position.copy(direction).multiplyScalar(1.12)

  group.add(shaft, arrow, labelSprite)
  return group
}

function makeAxisWidget() {
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 20)
  const group = new THREE.Group()

  group.add(makeAxis(new THREE.Vector3(1, 0, 0), '#ff8a6a', 'X'))
  group.add(makeAxis(new THREE.Vector3(0, 1, 0), '#79d6a3', 'Y'))
  group.add(makeAxis(new THREE.Vector3(0, 0, 1), '#7fb5ff', 'Z'))

  const origin = new THREE.Mesh(
    new THREE.SphereGeometry(0.07, 24, 16),
    new THREE.MeshBasicMaterial({ color: '#dbe7ef' }),
  )
  group.add(origin)
  scene.add(group)

  return { scene, camera, group }
}

function enhanceColors(source: Float32Array, count: number) {
  const display = new Float32Array(count * 3)
  const expected = count * 3

  for (let i = 0; i < expected; i += 3) {
    const r = source[i] ?? 0.78
    const g = source[i + 1] ?? 0.78
    const b = source[i + 2] ?? 0.78
    const average = (r + g + b) / 3

    const saturatedR = average + (r - average) * 1.18
    const saturatedG = average + (g - average) * 1.16
    const saturatedB = average + (b - average) * 1.2

    display[i] = Math.pow(clamp01(saturatedR * 1.08 + 0.045), 0.92)
    display[i + 1] = Math.pow(clamp01(saturatedG * 1.08 + 0.045), 0.92)
    display[i + 2] = Math.pow(clamp01(saturatedB * 1.1 + 0.055), 0.9)
  }

  return display
}

function makeFocusBox(fullBox: THREE.Box3, xs: Float32Array, ys: Float32Array, zs: Float32Array, count: number) {
  xs.sort()
  ys.sort()
  zs.sort()

  const lower = Math.max(0, Math.floor(count * 0.015))
  const upper = Math.min(count - 1, Math.ceil(count * 0.985))
  const focusBox = new THREE.Box3(
    new THREE.Vector3(xs[lower], ys[lower], zs[lower]),
    new THREE.Vector3(xs[upper], ys[upper], zs[upper]),
  )
  const focusSize = focusBox.getSize(new THREE.Vector3())
  const fullSize = fullBox.getSize(new THREE.Vector3())
  const focusMax = Math.max(focusSize.x, focusSize.y, focusSize.z)
  const fullMax = Math.max(fullSize.x, fullSize.y, fullSize.z, 1)

  if (!Number.isFinite(focusMax) || focusMax < fullMax * 0.02) {
    return fullBox.clone()
  }

  focusBox.expandByScalar(Math.max(focusMax * 0.08, fullMax * 0.004))
  return focusBox
}

function getAxisIndex(value: number, min: number, size: number, bins: number) {
  if (size <= 1e-9) return 0
  return THREE.MathUtils.clamp(Math.floor(((value - min) / size) * bins), 0, bins - 1)
}

function makeDenseFocusBox(positions: Float32Array, baseBox: THREE.Box3, count: number) {
  const baseSize = baseBox.getSize(new THREE.Vector3())
  const baseMax = Math.max(baseSize.x, baseSize.y, baseSize.z, 1)
  if (!Number.isFinite(baseMax) || baseMax <= 0) return baseBox.clone()

  const bins = 24
  const binCounts = new Uint32Array(bins * bins * bins)
  let bestIndex = 0
  let bestCount = 0
  let validCount = 0
  const point = new THREE.Vector3()

  for (let i = 0; i < count; i++) {
    const source = i * 3
    point.set(positions[source], positions[source + 1], positions[source + 2])
    if (!baseBox.containsPoint(point)) continue

    const ix = getAxisIndex(point.x, baseBox.min.x, baseSize.x, bins)
    const iy = getAxisIndex(point.y, baseBox.min.y, baseSize.y, bins)
    const iz = getAxisIndex(point.z, baseBox.min.z, baseSize.z, bins)
    const index = ix + iy * bins + iz * bins * bins
    const nextCount = ++binCounts[index]
    validCount++

    if (nextCount > bestCount) {
      bestCount = nextCount
      bestIndex = index
    }
  }

  if (validCount < 32 || bestCount < 4) return baseBox.clone()

  const bestIz = Math.floor(bestIndex / (bins * bins))
  const bestIy = Math.floor((bestIndex - bestIz * bins * bins) / bins)
  const bestIx = bestIndex % bins
  const denseCenter = new THREE.Vector3(
    baseBox.min.x + ((bestIx + 0.5) / bins) * baseSize.x,
    baseBox.min.y + ((bestIy + 0.5) / bins) * baseSize.y,
    baseBox.min.z + ((bestIz + 0.5) / bins) * baseSize.z,
  )
  const safeSize = new THREE.Vector3(
    Math.max(baseSize.x, baseMax * 0.02),
    Math.max(baseSize.y, baseMax * 0.02),
    Math.max(baseSize.z, baseMax * 0.02),
  )
  const distances = new Float32Array(validCount)
  let distanceCount = 0

  for (let i = 0; i < count; i++) {
    const source = i * 3
    point.set(positions[source], positions[source + 1], positions[source + 2])
    if (!baseBox.containsPoint(point)) continue

    const dx = (point.x - denseCenter.x) / safeSize.x
    const dy = (point.y - denseCenter.y) / safeSize.y
    const dz = (point.z - denseCenter.z) / safeSize.z
    distances[distanceCount++] = dx * dx + dy * dy + dz * dz
  }

  const sortedDistances = distances.slice(0, distanceCount)
  sortedDistances.sort()
  const thresholdIndex = THREE.MathUtils.clamp(Math.floor(distanceCount * 0.28), 16, distanceCount - 1)
  const distanceThreshold = sortedDistances[thresholdIndex]
  const denseBox = new THREE.Box3()
  let denseCount = 0

  for (let i = 0; i < count; i++) {
    const source = i * 3
    point.set(positions[source], positions[source + 1], positions[source + 2])
    if (!baseBox.containsPoint(point)) continue

    const dx = (point.x - denseCenter.x) / safeSize.x
    const dy = (point.y - denseCenter.y) / safeSize.y
    const dz = (point.z - denseCenter.z) / safeSize.z
    if (dx * dx + dy * dy + dz * dz > distanceThreshold) continue

    denseBox.expandByPoint(point)
    denseCount++
  }

  const denseSize = denseBox.getSize(new THREE.Vector3())
  const denseMax = Math.max(denseSize.x, denseSize.y, denseSize.z)
  if (denseCount < Math.max(64, validCount * 0.04) || !Number.isFinite(denseMax) || denseMax < baseMax * 0.01) {
    return baseBox.clone()
  }

  denseBox.expandByScalar(Math.max(denseMax * 0.18, baseMax * 0.015))
  return denseBox
}

function splitCloudByFocus(
  positions: Float32Array,
  displayColors: Float32Array,
  focusBox: THREE.Box3,
  radius: number,
  count: number,
) {
  const primaryBox = focusBox.clone().expandByScalar(radius * 0.34)
  const primaryPositions = new Float32Array(count * 3)
  const primaryColors = new Float32Array(count * 3)
  const contextPositions = new Float32Array(count * 3)
  const contextColors = new Float32Array(count * 3)
  const probe = new THREE.Vector3()
  let primaryCount = 0
  let contextCount = 0

  for (let i = 0; i < count; i++) {
    const source = i * 3
    probe.set(positions[source], positions[source + 1], positions[source + 2])

    if (primaryBox.containsPoint(probe)) {
      const target = primaryCount * 3
      primaryPositions[target] = positions[source]
      primaryPositions[target + 1] = positions[source + 1]
      primaryPositions[target + 2] = positions[source + 2]
      primaryColors[target] = displayColors[source]
      primaryColors[target + 1] = displayColors[source + 1]
      primaryColors[target + 2] = displayColors[source + 2]
      primaryCount++
    } else {
      const target = contextCount * 3
      contextPositions[target] = positions[source]
      contextPositions[target + 1] = positions[source + 1]
      contextPositions[target + 2] = positions[source + 2]
      contextColors[target] = displayColors[source] * 0.72
      contextColors[target + 1] = displayColors[source + 1] * 0.78
      contextColors[target + 2] = displayColors[source + 2]
      contextCount++
    }
  }

  return {
    primaryPositions: primaryPositions.slice(0, primaryCount * 3),
    primaryColors: primaryColors.slice(0, primaryCount * 3),
    primaryCount,
    contextPositions: contextPositions.slice(0, contextCount * 3),
    contextColors: contextColors.slice(0, contextCount * 3),
    contextCount,
  }
}

// COLMAP convention (+X=right, +Y=down, +Z=forward) → Three.js (+X=right, +Y=up, +Z=backward)
function toViewerVector(value: [number, number, number]) {
  return new THREE.Vector3(value[0], -value[1], -value[2])
}

function cameraFrustumInViewer(camera: CameraPose, scale: number) {
  const center = toViewerVector(camera.center)
  const corners = camera.corners.map((corner) => {
    const rawCorner = toViewerVector(corner)
    return center.clone().add(rawCorner.sub(center).multiplyScalar(scale))
  })

  return { center, corners }
}

function addLineSegments(
  container: THREE.Object3D,
  vertices: number[],
  color: string,
  opacity: number,
  renderOrder: number,
  depthTest = true,
) {
  if (!vertices.length) return

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthTest,
    depthWrite: false,
  })
  const lines = new THREE.LineSegments(geometry, material)
  lines.renderOrder = renderOrder
  container.add(lines)
}

function addCameraFrustumOverlay(container: THREE.Object3D, cameras: CameraPose[], radius: number) {
  if (!cameras.length) return

  const edgeVertices: number[] = []
  const rayVertices: number[] = []
  const directionVertices: number[] = []
  const planeVertices: number[] = []
  const frustumScale = THREE.MathUtils.clamp(radius * 0.01, radius * 0.002, radius * 0.03)

  const pushVertex = (vertices: number[], point: THREE.Vector3) => {
    vertices.push(point.x, point.y, point.z)
  }

  const pushSegment = (vertices: number[], a: THREE.Vector3, b: THREE.Vector3) => {
    pushVertex(vertices, a)
    pushVertex(vertices, b)
  }

  const pushTriangle = (a: THREE.Vector3, b: THREE.Vector3, c: THREE.Vector3) => {
    pushVertex(planeVertices, a)
    pushVertex(planeVertices, b)
    pushVertex(planeVertices, c)
  }

  for (const camera of cameras) {
    const { center, corners } = cameraFrustumInViewer(camera, frustumScale)
    if (corners.length < 4) continue

    pushTriangle(corners[0], corners[1], corners[2])
    pushTriangle(corners[0], corners[2], corners[3])

    pushSegment(edgeVertices, corners[0], corners[1])
    pushSegment(edgeVertices, corners[1], corners[2])
    pushSegment(edgeVertices, corners[2], corners[3])
    pushSegment(edgeVertices, corners[3], corners[0])

    pushSegment(rayVertices, center, corners[0])
    pushSegment(rayVertices, center, corners[1])
    pushSegment(rayVertices, center, corners[2])
    pushSegment(rayVertices, center, corners[3])

    const imageCenter = new THREE.Vector3()
    for (const corner of corners) imageCenter.add(corner)
    imageCenter.multiplyScalar(0.25)
    pushSegment(directionVertices, center, center.clone().lerp(imageCenter, 1.18))
  }

  if (planeVertices.length) {
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(planeVertices, 3))
    const material = new THREE.MeshBasicMaterial({
      color: '#3fe765',
      transparent: true,
      opacity: 0.07,
      side: THREE.DoubleSide,
      depthTest: true,
      depthWrite: false,
    })
    const planes = new THREE.Mesh(geometry, material)
    planes.renderOrder = 2
    container.add(planes)
  }

  addLineSegments(container, rayVertices, '#ff8758', 0.24, 3, false)
  addLineSegments(container, directionVertices, '#ff7048', 0.44, 4, false)
  addLineSegments(container, edgeVertices, '#63f47f', 0.5, 5, false)
}

function addCameraPoseOverlay(container: THREE.Object3D, cameras: CameraPose[], radius: number, mode: PoseDisplayMode) {
  if (!cameras.length || mode === 'hidden') return
  addCameraFrustumOverlay(container, cameras, radius)
}

function disposeObject(object: THREE.Object3D) {
  object.traverse((node) => {
    const item = node as THREE.Mesh | THREE.Points | THREE.LineSegments | THREE.Sprite
    item.geometry?.dispose()

    const materials = Array.isArray(item.material) ? item.material : item.material ? [item.material] : []
    for (const material of materials) {
      const withMap = material as THREE.Material & { map?: THREE.Texture }
      withMap.map?.dispose()
      material.dispose()
    }
  })
}

function clearObjectChildren(object: THREE.Object3D) {
  for (const child of [...object.children]) {
    object.remove(child)
    disposeObject(child)
  }
}

export default function PointCloudViewer({ points, colors, numPoints, totalPoints, cameras = [], className }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const camRef = useRef<THREE.PerspectiveCamera | null>(null)
  const ctrlRef = useRef<OrbitControls | null>(null)
  const initRef = useRef<SavedView | null>(null)
  const poseOverlayRef = useRef<THREE.Group | null>(null)
  const poseRadiusRef = useRef(1)
  const [poseDisplayMode, setPoseDisplayMode] = useState<PoseDisplayMode>('frustum')

  const resetView = useCallback(() => {
    const camera = camRef.current
    const controls = ctrlRef.current
    const initial = initRef.current
    if (!camera || !controls || !initial) return

    const startPosition = camera.position.clone()
    const startTarget = controls.target.clone()
    const startedAt = performance.now()

    const loop = (now: number) => {
      const progress = Math.min((now - startedAt) / 620, 1)
      const eased = 1 - Math.pow(1 - progress, 3)

      camera.position.lerpVectors(startPosition, initial.position, eased)
      controls.target.lerpVectors(startTarget, initial.target, eased)
      controls.update()

      if (progress < 1) requestAnimationFrame(loop)
    }

    requestAnimationFrame(loop)
  }, [])

  useEffect(() => {
    const el = mountRef.current
    if (!el || !points || !colors || numPoints === 0) return
    el.innerHTML = ''

    let viewWidth = el.clientWidth || 960
    let viewHeight = el.clientHeight || 640

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#0f1316')
    const poseOverlay = new THREE.Group()
    poseOverlay.name = 'camera-pose-overlay'
    scene.add(poseOverlay)
    poseOverlayRef.current = poseOverlay

    const camera = new THREE.PerspectiveCamera(50, viewWidth / viewHeight, 0.01, 5000)
    camRef.current = camera

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    renderer.setSize(viewWidth, viewHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.16
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.width = '100%'
    renderer.domElement.style.height = '100%'
    el.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.rotateSpeed = 0.62
    controls.zoomSpeed = 0.72
    controls.panSpeed = 0.86
    controls.screenSpacePanning = true
    ctrlRef.current = controls

    const positions = new Float32Array(numPoints * 3)
    const xs = new Float32Array(numPoints)
    const ys = new Float32Array(numPoints)
    const zs = new Float32Array(numPoints)
    const box = new THREE.Box3()
    const probe = new THREE.Vector3()

    for (let i = 0; i < numPoints; i++) {
      // COLMAP convention (+Y=down, +Z=forward) → Three.js (+Y=up, +Z=backward)
      const x = points[i * 3]
      const y = -points[i * 3 + 1]      // flip Y
      const z = -points[i * 3 + 2]      // flip Z

      positions[i * 3] = x
      positions[i * 3 + 1] = y
      positions[i * 3 + 2] = z
      xs[i] = x
      ys[i] = y
      zs[i] = z

      probe.set(x, y, z)
      box.expandByPoint(probe)
    }

    const robustBox = makeFocusBox(box, xs, ys, zs, numPoints)
    const focusBox = makeDenseFocusBox(positions, robustBox, numPoints)
    const center = focusBox.getCenter(new THREE.Vector3())
    const size = focusBox.getSize(new THREE.Vector3())
    const maxDim = Math.max(size.x, size.y, size.z, 1)
    const sphere = focusBox.getBoundingSphere(new THREE.Sphere())
    const radius = Math.max(sphere.radius, maxDim * 0.5, 1)
    const fullSphere = box.getBoundingSphere(new THREE.Sphere())
    const fullRadius = Math.max(fullSphere.radius, radius)
    const floorY = focusBox.min.y - radius * 0.045
    poseRadiusRef.current = radius

    scene.fog = new THREE.Fog('#0f1316', radius * 4.2, radius * 10.5)

    const gridSize = Math.pow(2, Math.ceil(Math.log2(maxDim * 1.35)))
    const divisions = THREE.MathUtils.clamp(Math.round(gridSize / Math.max(maxDim / 36, 0.01)), 24, 96)
    const grid = new THREE.GridHelper(gridSize, divisions, '#536772', '#222a30')
    grid.position.set(center.x, floorY, center.z)
    const gridMaterial = grid.material as THREE.LineBasicMaterial
    gridMaterial.transparent = true
    gridMaterial.opacity = 0.34
    gridMaterial.depthWrite = false
    scene.add(grid)

    const displayColors = enhanceColors(colors, numPoints)
    const cloudParts = splitCloudByFocus(positions, displayColors, focusBox, radius, numPoints)
    const pointTexture = makePointTexture()
    const pointSize = THREE.MathUtils.clamp(1.45 + Math.log10(Math.max(numPoints, 10)) * 0.05, 1.55, 1.82)

    if (cloudParts.contextCount > 0) {
      const contextGeometry = new THREE.BufferGeometry()
      contextGeometry.setAttribute('position', new THREE.BufferAttribute(cloudParts.contextPositions, 3))
      contextGeometry.setAttribute('color', new THREE.BufferAttribute(cloudParts.contextColors, 3))
      contextGeometry.computeBoundingSphere()

      const contextMaterial = new THREE.PointsMaterial({
        size: Math.max(1, pointSize * 0.62),
        vertexColors: true,
        sizeAttenuation: false,
        map: pointTexture,
        transparent: true,
        opacity: 0.18,
        alphaTest: 0.04,
        depthWrite: true,
      })
      scene.add(new THREE.Points(contextGeometry, contextMaterial))
    }

    const primaryGeometry = new THREE.BufferGeometry()
    primaryGeometry.setAttribute('position', new THREE.BufferAttribute(cloudParts.primaryPositions, 3))
    primaryGeometry.setAttribute('color', new THREE.BufferAttribute(cloudParts.primaryColors, 3))
    primaryGeometry.computeBoundingSphere()

    const primaryMaterial = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      sizeAttenuation: false,
      map: pointTexture,
      transparent: true,
      opacity: 0.84,
      alphaTest: 0.05,
      depthWrite: true,
    })
    scene.add(new THREE.Points(primaryGeometry, primaryMaterial))

    const axisWidget = makeAxisWidget()
    const fov = THREE.MathUtils.degToRad(camera.fov)
    const distance = Math.max(radius / Math.sin(fov / 2), maxDim) * 1.12
    const viewDirection = new THREE.Vector3(0.72, 0.42, 0.88).normalize()

    camera.near = Math.max(radius / 1200, 0.01)
    camera.far = Math.max(fullRadius * 8, radius * 80, 5000)
    camera.position.copy(center).addScaledVector(viewDirection, distance)
    camera.updateProjectionMatrix()

    controls.target.copy(center)
    controls.minDistance = Math.max(radius * 0.12, 0.05)
    controls.maxDistance = Math.max(fullRadius * 8, radius * 22, 100)
    controls.update()

    initRef.current = {
      position: camera.position.clone(),
      target: center.clone(),
    }

    let animationFrame = 0
    const render = () => {
      animationFrame = requestAnimationFrame(render)
      controls.update()

      renderer.setScissorTest(false)
      renderer.setViewport(0, 0, viewWidth, viewHeight)
      renderer.render(scene, camera)

      const widgetSize = Math.min(186, Math.max(146, Math.round(Math.min(viewWidth, viewHeight) * 0.28)))
      const widgetX = viewWidth - widgetSize - 8
      const widgetY = 10
      const direction = camera.position.clone().sub(controls.target).normalize()

      axisWidget.camera.position.copy(direction.multiplyScalar(5.6))
      axisWidget.camera.up.copy(camera.up)
      axisWidget.camera.lookAt(0, 0, 0)

      renderer.autoClear = false
      renderer.clearDepth()
      renderer.setScissor(widgetX, widgetY, widgetSize, widgetSize)
      renderer.setViewport(widgetX, widgetY, widgetSize, widgetSize)
      renderer.setScissorTest(true)
      renderer.render(axisWidget.scene, axisWidget.camera)
      renderer.setScissorTest(false)
      renderer.autoClear = true
    }
    render()

    const onResize = () => {
      viewWidth = el.clientWidth || 960
      viewHeight = el.clientHeight || 640

      camera.aspect = viewWidth / viewHeight
      camera.updateProjectionMatrix()
      renderer.setSize(viewWidth, viewHeight)
    }

    const resizeObserver = new ResizeObserver(onResize)
    resizeObserver.observe(el)
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(animationFrame)
      resizeObserver.disconnect()
      window.removeEventListener('resize', onResize)

      controls.dispose()
      disposeObject(scene)
      disposeObject(axisWidget.scene)
      renderer.dispose()
      el.innerHTML = ''
      camRef.current = null
      ctrlRef.current = null
      initRef.current = null
      poseOverlayRef.current = null
      poseRadiusRef.current = 1
    }
  }, [points, colors, numPoints])

  useEffect(() => {
    const overlay = poseOverlayRef.current
    if (!overlay) return

    clearObjectChildren(overlay)
    addCameraPoseOverlay(overlay, cameras, poseRadiusRef.current, poseDisplayMode)

    return () => {
      clearObjectChildren(overlay)
    }
  }, [cameras, poseDisplayMode, points, colors, numPoints])

  const actualTotalPoints = totalPoints ?? numPoints
  const pointCountValue = formatPointCount(actualTotalPoints)

  return (
    <div
      className={className}
      style={{ width: '100%', height: '100%', minHeight: 400, position: 'relative', overflow: 'hidden' }}
    >
      <div
        ref={mountRef}
        style={{
          width: '100%',
          height: '100%',
          background: '#0f1316',
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          zIndex: 4,
          background:
            'linear-gradient(180deg, rgba(255,255,255,0.045) 0%, rgba(255,255,255,0) 24%), radial-gradient(ellipse at center, rgba(255,255,255,0) 46%, rgba(0,0,0,0.28) 100%)',
        }}
      />
      <div className="absolute bottom-4 left-4 flex items-center gap-2" style={{ zIndex: 10 }}>
        <div className="pointer-events-none flex items-center gap-2 rounded-comfortable border border-white/[0.08] bg-black/40 px-3 py-2 text-[11px] font-mono text-white/45 shadow-2xl backdrop-blur">
          <span className="h-1.5 w-1.5 rounded-full bg-terracotta shadow-[0_0_14px_rgba(201,100,66,0.8)]" />
          <span className="text-white/25">点数</span>
          <span className="text-white/70">{pointCountValue}</span>
        </div>
        {cameras.length > 0 && (
          <div className="pointer-events-none flex items-center gap-2 rounded-comfortable border border-white/[0.08] bg-black/40 px-3 py-2 text-[11px] font-mono text-white/45 shadow-2xl backdrop-blur">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{
                background: poseDisplayMode === 'hidden' ? '#7b8791' : '#35e05a',
                boxShadow:
                  poseDisplayMode === 'hidden'
                    ? '0 0 10px rgba(123,135,145,0.45)'
                    : '0 0 14px rgba(53,224,90,0.75)',
              }}
            />
            <span className="text-white/25">相机</span>
            <span className="text-white/70">{formatPointCount(cameras.length)}</span>
          </div>
        )}
        {cameras.length > 0 && (
          <div className="flex overflow-hidden rounded-comfortable border border-white/[0.08] bg-black/40 p-0.5 text-[11px] font-mono shadow-2xl backdrop-blur">
            {([
              ['frustum', '视锥'],
              ['hidden', '隐藏'],
            ] as const).map(([mode, label]) => (
              <button
                key={mode}
                onClick={() => setPoseDisplayMode(mode)}
                className={`rounded-subtle px-2.5 py-1.5 transition-colors ${
                  poseDisplayMode === mode
                    ? 'bg-white/[0.12] text-white/80'
                    : 'text-white/35 hover:bg-white/[0.06] hover:text-white/60'
                }`}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        )}
        <button
          onClick={resetView}
          className="flex h-9 w-9 items-center justify-center rounded-comfortable border border-white/[0.08] bg-black/40 text-white/45 shadow-2xl backdrop-blur transition-colors hover:border-white/[0.16] hover:text-white/75"
          title="重置视角"
          type="button"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
