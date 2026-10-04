import { describe, expect, it, vi } from 'vitest'
import {
  anchorSelector,
  guardTourLayer,
  isInsideTourLayer,
  TOUR_ANCHORS,
  TOUR_LAYER_ATTR,
  tourAnchor,
} from './tour-anchors'

describe('якоря обучения', () => {
  it('строит селекторы для имени, вложенного якоря и произвольного селектора', () => {
    expect(anchorSelector(TOUR_ANCHORS.sourcesAdd)).toBe('[data-tour="sources.add"]')
    expect(anchorSelector({ name: 'question.answer', within: '[data-question-id="q1"]' })).toBe(
      '[data-question-id="q1"] [data-tour="question.answer"]',
    )
    expect(anchorSelector({ name: 'run.build' })).toBe('[data-tour="run.build"]')
    expect(anchorSelector({ selector: '[data-question-id]:first-of-type' })).toBe(
      '[data-question-id]:first-of-type',
    )
  })

  it('tourAnchor даёт атрибут для спреда', () => {
    expect(tourAnchor('run.build')).toEqual({ 'data-tour': 'run.build' })
  })

  it('guardTourLayer отменяет событие только внутри слоя обучения', () => {
    const layer = document.createElement('div')
    layer.setAttribute(TOUR_LAYER_ATTR, '')
    const inner = document.createElement('button')
    layer.append(inner)
    document.body.append(layer)
    const outer = document.createElement('div')
    document.body.append(outer)

    const inside = { target: inner, preventDefault: vi.fn() }
    guardTourLayer(inside)
    expect(inside.preventDefault).toHaveBeenCalledOnce()
    expect(isInsideTourLayer(inner)).toBe(true)

    const outside = { target: outer, preventDefault: vi.fn() }
    guardTourLayer(outside)
    expect(outside.preventDefault).not.toHaveBeenCalled()
    expect(isInsideTourLayer(null)).toBe(false)
    layer.remove()
    outer.remove()
  })
})
