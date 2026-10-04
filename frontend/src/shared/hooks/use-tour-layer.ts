import { useEffect } from 'react'
import { trackTourLayerPointer } from '@/shared/lib/tour-anchors'

/** Слой обучения (затемнение, карточка, кольцо) на экране: следим, где началось нажатие. */
export function useTourLayerTracking(): void {
  useEffect(() => trackTourLayerPointer(), [])
}
