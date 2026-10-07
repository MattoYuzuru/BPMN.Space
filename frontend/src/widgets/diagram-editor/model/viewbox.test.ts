import {
  cubicBezier,
  fitViewbox,
  focusViewbox,
  gridStep,
  interpolateViewbox,
  parseCubicBezier,
  parseDuration,
  scaleOf,
  unionBox,
  zoomViewbox,
} from './viewbox'

const OUTER = { width: 1000, height: 500 }
const center = (box: { x: number; y: number; width: number; height: number }) => [
  box.x + box.width / 2,
  box.y + box.height / 2,
]

describe('fitViewbox', () => {
  it('вписывает большую схему с отступами и центрирует её', () => {
    const bbox = { x: 0, y: 0, width: 3000, height: 1200 }
    const viewbox = fitViewbox(OUTER, bbox, 50)
    expect(scaleOf(OUTER, viewbox)).toBeCloseTo(Math.min(900 / 3000, 400 / 1200))
    expect(center(viewbox)).toEqual([1500, 600])
  })

  it('маленькую схему не увеличивает больше 100 %', () => {
    const viewbox = fitViewbox(OUTER, { x: 10, y: 10, width: 100, height: 50 })
    expect(scaleOf(OUTER, viewbox)).toBe(1)
  })

  it('большой процесс полностью помещается при обзоре ниже 20%', () => {
    const bbox = { x: 500, y: 100, width: 10_000, height: 2500 }
    const viewbox = fitViewbox(OUTER, bbox, 50)
    expect(scaleOf(OUTER, viewbox)).toBeCloseTo(0.09)
    expect(viewbox.x).toBeLessThan(bbox.x)
    expect(viewbox.y).toBeLessThan(bbox.y)
    expect(viewbox.x + viewbox.width).toBeGreaterThan(bbox.x + bbox.width)
    expect(viewbox.y + viewbox.height).toBeGreaterThan(bbox.y + bbox.height)
    const zoomed = zoomViewbox(OUTER, viewbox, 1.25)
    expect(scaleOf(OUTER, zoomed)).toBeCloseTo(0.1125)
  })
})

describe('focusViewbox', () => {
  const current = { x: 0, y: 0, width: 1000, height: 500 }

  it('сохраняет масштаб и центрирует элемент', () => {
    const viewbox = focusViewbox(OUTER, current, { x: 2000, y: 900, width: 100, height: 80 })
    expect(scaleOf(OUTER, viewbox)).toBe(1)
    expect(center(viewbox)).toEqual([2050, 940])
  })

  it('отдаляет, если элемент не помещается', () => {
    const viewbox = focusViewbox(OUTER, current, { x: 0, y: 0, width: 3000, height: 100 })
    expect(scaleOf(OUTER, viewbox)).toBeLessThan(1)
  })

  it('приближает до читаемого масштаба, если схема слишком мелкая', () => {
    const far = { x: 0, y: 0, width: 4000, height: 2000 }
    const viewbox = focusViewbox(OUTER, far, { x: 100, y: 100, width: 100, height: 80 })
    expect(scaleOf(OUTER, viewbox)).toBe(1)
  })
})

describe('zoomViewbox', () => {
  it('масштабирует вокруг центра окна и ограничивает масштаб', () => {
    const current = { x: 0, y: 0, width: 1000, height: 500 }
    const zoomed = zoomViewbox(OUTER, current, 2)
    expect(scaleOf(OUTER, zoomed)).toBe(2)
    expect(center(zoomed)).toEqual(center(current))
    expect(scaleOf(OUTER, zoomViewbox(OUTER, current, 100))).toBe(4)
    expect(scaleOf(OUTER, zoomViewbox(OUTER, current, 0.001))).toBe(0.2)
  })
})

describe('interpolateViewbox', () => {
  it('на концах совпадает с исходным и целевым, масштаб меняется по логарифму', () => {
    const from = { x: 0, y: 0, width: 1000, height: 500 }
    const to = { x: 400, y: 200, width: 250, height: 125 }
    const start = interpolateViewbox(from, to, 0)
    expect(start.x).toBeCloseTo(0)
    expect(start.width).toBeCloseTo(1000)
    const end = interpolateViewbox(from, to, 1)
    expect(end.x).toBeCloseTo(400)
    expect(end.width).toBeCloseTo(250)
    expect(interpolateViewbox(from, to, 0.5).width).toBeCloseTo(500)
  })
})

describe('unionBox и gridStep', () => {
  it('объединяет прямоугольники', () => {
    expect(unionBox([])).toBeNull()
    expect(
      unionBox([
        { x: 10, y: 20, width: 10, height: 10 },
        { x: 0, y: 25, width: 5, height: 30 },
      ]),
    ).toEqual({ x: 0, y: 20, width: 20, height: 35 })
  })

  it('удваивает шаг сетки, пока точки не перестанут сливаться', () => {
    expect(gridStep(24)).toBe(24)
    expect(gridStep(6)).toBe(12)
    expect(gridStep(4.8)).toBeCloseTo(19.2)
    expect(gridStep(0)).toBe(12)
    expect(gridStep(Number.NaN)).toBe(12)
  })
})

describe('кривые и длительности из токенов', () => {
  it('cubic-bezier совпадает с CSS на краях и монотонен', () => {
    const ease = cubicBezier(0.22, 1, 0.36, 1)
    expect(ease(0)).toBe(0)
    expect(ease(1)).toBe(1)
    expect(ease(0.5)).toBeGreaterThan(0.85)
    let previous = 0
    for (let t = 0.05; t <= 1; t += 0.05) {
      expect(ease(t)).toBeGreaterThanOrEqual(previous)
      previous = ease(t)
    }
    expect(cubicBezier(0, 0, 1, 1)(0.3)).toBeCloseTo(0.3)
  })

  it('разбирает значения токенов и отвергает мусор', () => {
    expect(parseCubicBezier(' cubic-bezier(0.22, 1, 0.36, 1)')).toEqual([0.22, 1, 0.36, 1])
    expect(parseCubicBezier('ease-out')).toBeNull()
    expect(parseCubicBezier('cubic-bezier(1, 2)')).toBeNull()
    expect(parseDuration('320ms')).toBe(320)
    expect(parseDuration(' 0.2s')).toBe(200)
    expect(parseDuration('')).toBeNull()
  })
})
