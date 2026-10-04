import { useEffect, useState } from 'react'
import { anchorSelector, TOUR_ANCHORS } from '@/shared/lib/tour-anchors'
import type { TourPresence } from './context'

const NONE: TourPresence = {
  createSubmit: false,
  textContent: false,
  voiceCapture: false,
  shareCreate: false,
  shareCopy: false,
}

const PROBES: Record<keyof TourPresence, string> = {
  createSubmit: anchorSelector(TOUR_ANCHORS.createSubmit),
  textContent: anchorSelector(TOUR_ANCHORS.sourceTextContent),
  voiceCapture: anchorSelector(TOUR_ANCHORS.voiceCapture),
  shareCreate: anchorSelector(TOUR_ANCHORS.shareCreate),
  shareCopy: anchorSelector(TOUR_ANCHORS.shareCopy),
}

const POLL_MS = 250

function probe(): TourPresence {
  const result = { ...NONE }
  for (const [name, selector] of Object.entries(PROBES)) {
    result[name as keyof TourPresence] = document.querySelector(selector) !== null
  }
  return result
}

const same = (a: TourPresence, b: TourPresence) =>
  (Object.keys(a) as (keyof TourPresence)[]).every((key) => a[key] === b[key])

/**
 * Какие якоря окон сейчас есть на экране. Состояние окон живёт в фичах (локально или в их сторах),
 * а тур знает только `data-tour`: раз в 250 мс смотрим, открыто ли окно, пока тур идёт.
 */
export function useAnchorPresence(enabled: boolean): TourPresence {
  const [presence, setPresence] = useState(NONE)
  useEffect(() => {
    if (!enabled) {
      setPresence(NONE)
      return
    }
    const check = () => setPresence((current) => (same(current, probe()) ? current : probe()))
    check()
    const timer = window.setInterval(check, POLL_MS)
    return () => window.clearInterval(timer)
  }, [enabled])
  return presence
}
