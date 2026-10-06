import { clampNavigation, paddedBounds, projectViewport } from './minimap'

const bounds = { x: 100, y: 200, width: 800, height: 400 }

describe('навигация мини-картой', () => {
  it('ограничивает обе маленькие оси, не меняя масштаб', () => {
    expect(clampNavigation({ x: -200, y: 900, width: 200, height: 100 }, bounds)).toEqual({
      x: 100,
      y: 500,
      width: 200,
      height: 100,
    })
  })
  it('центрирует только ось, которая больше схемы', () => {
    expect(clampNavigation({ x: 900, y: 900, width: 1200, height: 100 }, bounds)).toEqual({
      x: -100,
      y: 500,
      width: 1200,
      height: 100,
    })
  })
  it('большая область не может увести схему с экрана', () => {
    expect(clampNavigation({ x: -9000, y: 9000, width: 1200, height: 800 }, bounds)).toEqual({
      x: -100,
      y: 0,
      width: 1200,
      height: 800,
    })
  })
  it('пустая схема имеет положительные границы с отступом', () => {
    expect(paddedBounds({ x: 0, y: 0, width: 0, height: 0 })).toEqual({
      x: -72,
      y: -72,
      width: 145,
      height: 145,
    })
  })
  it('вся рамка большой области видна внутри карты', () => {
    expect(
      projectViewport({ x: -2000, y: -2000, width: 8000, height: 8000 }, bounds, {
        width: 240,
        height: 140,
      }),
    ).toEqual({ x: 3, y: 3, width: 234, height: 134 })
  })
  it('учитывает пропорции SVG meet и смещение по вертикали', () => {
    expect(
      projectViewport({ x: 100, y: 200, width: 400, height: 200 }, bounds, {
        width: 240,
        height: 140,
      }),
    ).toEqual({ x: 3, y: 10, width: 117, height: 60 })
  })
  it('даже pan основного canvas за схему не выводит рамку за карту', () => {
    const box = projectViewport({ x: 5000, y: -5000, width: 200, height: 100 }, bounds, {
      width: 240,
      height: 140,
    })
    expect(box.x).toBeLessThanOrEqual(237)
    expect(box.y).toBeGreaterThanOrEqual(3)
    expect(box.width).toBe(2)
    expect(box.height).toBe(2)
  })
})
