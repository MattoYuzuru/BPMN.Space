import { useEffect, useRef } from 'react'
import {
  INITIAL_LENS_STATE,
  INITIAL_LENS_TARGET,
  isLensAllowed,
  isLensBlocked,
  LENS_MAGNIFY,
  LENS_RADIUS,
  type LensState,
  type LensTarget,
  lensNeedsFrame,
  placeOnPointer,
  stepLens,
} from './lens-model'

/**
 * Холст линзы сетки-подложки (WebGL2 без библиотек). Грузится лениво из <GridBackdrop interactive>.
 * Рисует ту же сетку, что CSS-слой pattern-grid (шаг --grid-size, сдвиг −1px, линия 1px), а вокруг
 * курсора «приподнимает» её: выборка сжимается к курсору. Кадры идут только пока сглаживание
 * не сошлось; в покое requestAnimationFrame не работает.
 */

const VERTEX = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`

const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 uResolution;
uniform float uDpr;
uniform vec2 uMouse;
uniform float uStrength;
uniform float uRadius;
uniform float uMagnify;
uniform float uGridSize;
uniform vec4 uLineColor;
uniform vec3 uAccentColor;
out vec4 outColor;

// Покрытие пикселя линией шириной 1 CSS px на периоде uGridSize; линия занимает [0, 1) периода.
float cover(float v) {
  float s = max(fwidth(v), 1e-4);
  float k = s * uDpr;
  float t = mod(v - 0.5 + uGridSize * 0.5, uGridSize) - uGridSize * 0.5;
  float d = abs(t);
  float overlap = min(d + s * 0.5, k * 0.5) - max(d - s * 0.5, -k * 0.5);
  return clamp(overlap / s, 0.0, 1.0);
}

void main() {
  vec2 p = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y) / uDpr;
  vec2 d = p - uMouse;
  float f = exp(-dot(d, d) / (uRadius * uRadius));
  vec2 q = uMouse + d * (1.0 - uMagnify * uStrength * f);
  vec2 v = q + 1.0;
  float c = max(cover(v.x), cover(v.y));
  float lens = uStrength * f;
  float a = min(uLineColor.a * c * (1.0 + 0.4 * lens), 1.0);
  vec3 rgb = mix(uLineColor.rgb, uAccentColor, 0.25 * lens);
  outColor = vec4(rgb * a, a);
}`

const UNIFORMS = [
  'uResolution',
  'uDpr',
  'uMouse',
  'uStrength',
  'uRadius',
  'uMagnify',
  'uGridSize',
  'uLineColor',
  'uAccentColor',
] as const
type UniformName = (typeof UNIFORMS)[number]

type Rgba = [number, number, number, number]

interface Program {
  gl: WebGL2RenderingContext
  uniforms: Record<UniformName, WebGLUniformLocation | null>
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader
  gl.deleteShader(shader)
  return null
}

function buildProgram(gl: WebGL2RenderingContext): Program | null {
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX)
  const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT)
  const program = gl.createProgram()
  if (!vertex || !fragment || !program) return null
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null
  // biome-ignore lint/correctness/useHookAtTopLevel: WebGL-метод useProgram, не React-хук
  gl.useProgram(program)
  gl.bindVertexArray(gl.createVertexArray())
  gl.clearColor(0, 0, 0, 0)
  const uniforms = Object.fromEntries(
    UNIFORMS.map((name) => [name, gl.getUniformLocation(program, name)]),
  ) as Program['uniforms']
  return { gl, uniforms }
}

let probe: CanvasRenderingContext2D | null = null

/**
 * Любой CSS-цвет (токены бывают в oklch) → RGBA 0..1 через 2D-контекст 1×1.
 * null — браузер не понял значение: тогда остаётся CSS-сетка.
 */
function parseColor(value: string): Rgba | null {
  if (!value) return null
  probe ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true })
  if (!probe) return null
  probe.canvas.width = probe.canvas.height = 1
  probe.fillStyle = 'black'
  probe.fillStyle = value
  const first = probe.fillStyle
  probe.fillStyle = 'white'
  probe.fillStyle = value
  if (first !== probe.fillStyle) return null
  probe.clearRect(0, 0, 1, 1)
  probe.fillRect(0, 0, 1, 1)
  const [r = 0, g = 0, b = 0, a = 0] = probe.getImageData(0, 0, 1, 1).data
  return [r / 255, g / 255, b / 255, a / 255]
}

export interface GridLensCanvasProps {
  /** Холст готов и нарисовал первый кадр (true) или недоступен/потерян (false) — CSS-сетку показать. */
  onActiveChange: (active: boolean) => void
  className?: string
}

export function GridLensCanvas({ onActiveChange, className }: GridLensCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const reportRef = useRef(onActiveChange)
  reportRef.current = onActiveChange

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const report = (active: boolean) => reportRef.current(active)

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const pointerQuery = window.matchMedia('(hover: hover) and (pointer: fine)')
    const allowed = () =>
      isLensAllowed({
        reducedMotion: motionQuery.matches,
        finePointerWithHover: pointerQuery.matches,
      })

    let program: Program | null = null
    let lineColor: Rgba = [0, 0, 0, 0]
    let accentColor: Rgba = [0, 0, 0, 1]
    let gridSize = 24
    let dpr = 1
    let state: LensState = INITIAL_LENS_STATE
    let target: LensTarget = INITIAL_LENS_TARGET
    let frame = 0
    let last = 0
    let live = false

    const readTokens = (): boolean => {
      const style = getComputedStyle(canvas)
      const line = parseColor(style.getPropertyValue('--grid-line').trim())
      const accent = parseColor(style.getPropertyValue('--color-accent').trim())
      if (!line || !accent) return false
      lineColor = line
      accentColor = accent
      gridSize = Number.parseFloat(style.getPropertyValue('--grid-size')) || 24
      return true
    }

    const size = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      const width = Math.max(1, Math.round(canvas.clientWidth * dpr))
      const height = Math.max(1, Math.round(canvas.clientHeight * dpr))
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width
        canvas.height = height
      }
    }

    const draw = () => {
      if (!program) return
      const { gl, uniforms: u } = program
      const rect = canvas.getBoundingClientRect()
      gl.viewport(0, 0, canvas.width, canvas.height)
      gl.clear(gl.COLOR_BUFFER_BIT)
      gl.uniform2f(u.uResolution, canvas.width, canvas.height)
      gl.uniform1f(u.uDpr, canvas.width / Math.max(rect.width, 1))
      gl.uniform2f(u.uMouse, state.x - rect.left, state.y - rect.top)
      gl.uniform1f(u.uStrength, state.strength)
      gl.uniform1f(u.uRadius, LENS_RADIUS)
      gl.uniform1f(u.uMagnify, LENS_MAGNIFY)
      gl.uniform1f(u.uGridSize, gridSize)
      gl.uniform4f(u.uLineColor, ...lineColor)
      gl.uniform3f(u.uAccentColor, accentColor[0], accentColor[1], accentColor[2])
      gl.drawArrays(gl.TRIANGLES, 0, 3)
      if (!live) {
        live = true
        report(true)
      }
    }

    const stop = () => {
      if (frame) cancelAnimationFrame(frame)
      frame = 0
      last = 0
    }

    const tick = (now: number) => {
      frame = 0
      state = stepLens(state, target, last ? now - last : 1000 / 60)
      last = now
      draw()
      if (lensNeedsFrame(state, target)) frame = requestAnimationFrame(tick)
      else last = 0
    }

    const wake = () => {
      if (!frame && program && !document.hidden && lensNeedsFrame(state, target)) {
        frame = requestAnimationFrame(tick)
      }
    }

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      state = placeOnPointer(state, event.clientX, event.clientY)
      target = {
        x: event.clientX,
        y: event.clientY,
        active: !isLensBlocked(event.target),
      }
      wake()
    }
    const onPointerLeave = () => {
      target = { ...target, active: false }
      wake()
    }

    const redraw = () => {
      size()
      draw()
    }

    const init = (): boolean => {
      const gl = canvas.getContext('webgl2', {
        alpha: true,
        premultipliedAlpha: true,
        antialias: false,
        depth: false,
        stencil: false,
        powerPreference: 'low-power',
      })
      if (!gl || !readTokens()) return false
      program = buildProgram(gl)
      if (!program) return false
      redraw()
      return true
    }

    const teardownWebgl = () => {
      stop()
      program = null
      if (live) report(false)
      live = false
    }

    const onContextLost = (event: Event) => {
      event.preventDefault()
      teardownWebgl()
    }
    const onContextRestored = () => {
      if (allowed() && init()) wake()
    }

    const onThemeChange = () => {
      if (program && readTokens()) draw()
    }

    const onEnvironmentChange = () => {
      if (allowed()) {
        if (!program && init()) wake()
      } else {
        teardownWebgl()
      }
    }

    // Курсор подхватится первым pointermove, размер — ResizeObserver.
    if (allowed()) init()

    const resizeObserver = new ResizeObserver(() => {
      if (program) redraw()
    })
    resizeObserver.observe(canvas)
    const themeObserver = new MutationObserver(onThemeChange)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    let dprQuery: MediaQueryList | null = null
    const watchDpr = () => {
      dprQuery?.removeEventListener('change', onDprChange)
      dprQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`)
      dprQuery.addEventListener('change', onDprChange)
    }
    function onDprChange() {
      if (program) redraw()
      watchDpr()
    }
    watchDpr()

    const onVisibility = () => {
      if (document.hidden) stop()
      else wake()
    }

    window.addEventListener('pointermove', onPointerMove, { passive: true })
    document.documentElement.addEventListener('pointerleave', onPointerLeave)
    document.addEventListener('visibilitychange', onVisibility)
    canvas.addEventListener('webglcontextlost', onContextLost)
    canvas.addEventListener('webglcontextrestored', onContextRestored)
    motionQuery.addEventListener('change', onEnvironmentChange)
    pointerQuery.addEventListener('change', onEnvironmentChange)

    return () => {
      stop()
      resizeObserver.disconnect()
      themeObserver.disconnect()
      dprQuery?.removeEventListener('change', onDprChange)
      window.removeEventListener('pointermove', onPointerMove)
      document.documentElement.removeEventListener('pointerleave', onPointerLeave)
      document.removeEventListener('visibilitychange', onVisibility)
      canvas.removeEventListener('webglcontextlost', onContextLost)
      canvas.removeEventListener('webglcontextrestored', onContextRestored)
      motionQuery.removeEventListener('change', onEnvironmentChange)
      pointerQuery.removeEventListener('change', onEnvironmentChange)
      if (live) report(false)
    }
  }, [])

  return <canvas ref={canvasRef} className={className} />
}

export default GridLensCanvas
