import { PREFETCH_THRESHOLD, sentinelIndex, shouldLoadMore } from './infinite-scroll'

describe('sentinelIndex', () => {
  it('ставит сторожа на 90 % загруженного', () => {
    expect(PREFETCH_THRESHOLD).toBe(0.9)
    expect(sentinelIndex(20)).toBe(18)
    expect(sentinelIndex(12)).toBe(10)
    expect(sentinelIndex(1)).toBe(0)
    expect(sentinelIndex(0)).toBe(0)
  })

  it('в сетке выравнивает на начало ряда', () => {
    // 24 карточки по 4 в ряд: 90 % — индекс 21, начало его ряда — 20.
    expect(sentinelIndex(24, 4)).toBe(20)
    expect(sentinelIndex(36, 3)).toBe(30)
    expect(sentinelIndex(12, 4)).toBe(8)
  })

  it('не выходит за пределы списка', () => {
    expect(sentinelIndex(3, 4)).toBe(0)
    expect(sentinelIndex(5, 1, 1.5)).toBe(4)
  })
})

describe('shouldLoadMore', () => {
  it('грузит, только когда сторож виден, есть страница и ничего не грузится', () => {
    const base = { sentinelVisible: true, hasNextPage: true, isFetching: false }
    expect(shouldLoadMore(base)).toBe(true)
    expect(shouldLoadMore({ ...base, sentinelVisible: false })).toBe(false)
    expect(shouldLoadMore({ ...base, hasNextPage: false })).toBe(false)
    expect(shouldLoadMore({ ...base, isFetching: true })).toBe(false)
  })
})
