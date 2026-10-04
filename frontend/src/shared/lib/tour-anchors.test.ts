import { describe, expect, it, vi } from 'vitest'
import {
  anchorSelector,
  guardTourLayer,
  isInsideTourLayer,
  TOUR_ANCHORS,
  TOUR_LAYER_ATTR,
  tourAnchor,
  trackTourLayerPointer,
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

  it('касание: нажатие началось в слое, а кнопка к проверке «клика снаружи» уже исчезла', () => {
    const release = trackTourLayerPointer()
    const layer = document.createElement('div')
    layer.setAttribute(TOUR_LAYER_ATTR, '')
    const button = document.createElement('button')
    layer.append(button)
    document.body.append(layer)
    button.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    // шаг сменился: кнопка карточки вынута из DOM до проверки на click
    button.remove()
    layer.remove()
    const event = {
      type: 'dismissableLayer.pointerDownOutside',
      target: button,
      preventDefault: vi.fn(),
    }
    guardTourLayer(event)
    expect(event.preventDefault).toHaveBeenCalledOnce()
    release()
    // слой снят: память о нажатии сброшена
    const after = { ...event, preventDefault: vi.fn() }
    guardTourLayer(after)
    expect(after.preventDefault).not.toHaveBeenCalled()
  })
})
