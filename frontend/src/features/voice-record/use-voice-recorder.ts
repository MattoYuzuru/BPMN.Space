import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderState =
  | { status: 'idle' }
  | { status: 'requesting' }
  | { status: 'recording' }
  | { status: 'recorded'; blob: Blob; durationSec: number }
  | { status: 'blocked'; reason: 'denied' | 'missing' | 'unsupported' | 'failed' }

/** Сколько значений уровня храним для визуализации. */
const LEVEL_HISTORY = 64
/** Как часто снимаем уровень, мс (≈ 16 значений в секунду — спокойная, не дёрганая картинка). */
const LEVEL_INTERVAL_MS = 60

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm']

/** Формат записи, который поддерживает браузер (webm/opus в Chromium, ogg/opus в Firefox). */
export function pickMimeType(isSupported: (type: string) => boolean): string | undefined {
  return MIME_CANDIDATES.find((type) => isSupported(type))
}

/**
 * Уровень сигнала 0..1 по отсчётам формы волны (128 — тишина): среднеквадратичное
 * отклонение с усилением, чтобы обычная речь занимала середину шкалы.
 */
export function levelFromSamples(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (let index = 0; index < samples.length; index += 1) {
    const value = ((samples[index] ?? 128) - 128) / 128
    sum += value * value
  }
  const rms = Math.sqrt(sum / samples.length)
  return Math.min(1, rms * 3.2)
}

function blockReason(error: unknown): Extract<RecorderState, { status: 'blocked' }>['reason'] {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'missing'
  return 'failed'
}

/**
 * Запись голоса: MediaRecorder (webm/ogg opus) и уровень сигнала через AnalyserNode.
 * Отказ в доступе к микрофону и его отсутствие — отдельные состояния, без системных окон.
 */
export function useVoiceRecorder({ maxSeconds = 600 }: { maxSeconds?: number } = {}) {
  const [state, setState] = useState<RecorderState>({ status: 'idle' })
  const [levels, setLevels] = useState<number[]>([])
  const [elapsed, setElapsed] = useState(0)
  const session = useRef<{
    stream: MediaStream
    recorder: MediaRecorder
    context: AudioContext
    timer: ReturnType<typeof setInterval>
    frame: number
    startedAt: number
    discard: boolean
  } | null>(null)
  // Поколение запроса микрофона: отмена, закрытие окна и повторный запуск делают прежние устаревшими.
  const generation = useRef(0)

  const cleanup = useCallback(() => {
    const current = session.current
    if (!current) return
    session.current = null
    clearInterval(current.timer)
    cancelAnimationFrame(current.frame)
    for (const track of current.stream.getTracks()) track.stop()
    void current.context.close().catch(() => undefined)
  }, [])

  const start = useCallback(async () => {
    if (session.current) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setState({ status: 'blocked', reason: 'unsupported' })
      return
    }
    setState({ status: 'requesting' })
    generation.current += 1
    const mine = generation.current
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      })
    } catch (error) {
      if (mine === generation.current) setState({ status: 'blocked', reason: blockReason(error) })
      return
    }
    if (mine !== generation.current) {
      // Пока ждали разрешение, запись отменили или окно закрыли: микрофон сразу отпускаем.
      for (const track of stream.getTracks()) track.stop()
      return
    }
    const mimeType = pickMimeType((type) => MediaRecorder.isTypeSupported(type))
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    const context = new AudioContext()
    const analyser = context.createAnalyser()
    analyser.fftSize = 1024
    analyser.smoothingTimeConstant = 0.6
    context.createMediaStreamSource(stream).connect(analyser)
    const samples = new Uint8Array(analyser.fftSize)
    const chunks: Blob[] = []
    const startedAt = performance.now()

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.onstop = () => {
      const discard = session.current?.discard ?? true
      const durationSec = (performance.now() - startedAt) / 1000
      cleanup()
      if (discard) return
      setState({
        status: 'recorded',
        blob: new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' }),
        durationSec: Math.round(durationSec * 10) / 10,
      })
    }

    let lastSample = 0
    const tick = (now: number) => {
      if (!session.current) return
      if (now - lastSample >= LEVEL_INTERVAL_MS) {
        lastSample = now
        analyser.getByteTimeDomainData(samples)
        const level = levelFromSamples(samples)
        setLevels((previous) => [...previous.slice(-(LEVEL_HISTORY - 1)), level])
      }
      session.current.frame = requestAnimationFrame(tick)
    }

    session.current = {
      stream,
      recorder,
      context,
      startedAt,
      discard: false,
      frame: 0,
      timer: setInterval(() => {
        const seconds = (performance.now() - startedAt) / 1000
        setElapsed(seconds)
        if (seconds >= maxSeconds) session.current?.recorder.stop()
      }, 200),
    }
    session.current.frame = requestAnimationFrame(tick)
    setLevels([])
    setElapsed(0)
    recorder.start(250)
    setState({ status: 'recording' })
  }, [cleanup, maxSeconds])

  const stop = useCallback(() => {
    const current = session.current
    if (current && current.recorder.state !== 'inactive') current.recorder.stop()
  }, [])

  const cancel = useCallback(() => {
    generation.current += 1
    const current = session.current
    if (current) {
      current.discard = true
      if (current.recorder.state !== 'inactive') current.recorder.stop()
      else cleanup()
    }
    setLevels([])
    setElapsed(0)
    setState({ status: 'idle' })
  }, [cleanup])

  // Закрыли окно во время записи — микрофон освобождается.
  useEffect(
    () => () => {
      generation.current += 1
      const current = session.current
      if (!current) return
      current.discard = true
      if (current.recorder.state !== 'inactive') current.recorder.stop()
      cleanup()
    },
    [cleanup],
  )

  return { state, levels, elapsed, start, stop, cancel }
}
