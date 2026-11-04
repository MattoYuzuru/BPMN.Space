import { MEDIA_METADATA_TIMEOUT_MS, mediaFileInfo } from './media-duration'

function fakeMedia(duration = Number.NaN) {
  const element = document.createElement('audio') as HTMLMediaElement
  Object.defineProperty(element, 'duration', { configurable: true, value: duration })
  return element
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:test')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.useRealTimers())

it('неизвестная длительность — 0, оценка не выдумывается, URL освобождается', async () => {
  vi.useFakeTimers()
  const element = fakeMedia()
  const promise = mediaFileInfo(
    new File(['x'], 'встреча.mp4', { type: 'video/mp4' }),
    () => element,
  )
  await vi.advanceTimersByTimeAsync(MEDIA_METADATA_TIMEOUT_MS)
  await expect(promise).resolves.toEqual({ durationSec: 0, hasVideo: true })
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
})

it('длительность из метаданных отдаётся и URL освобождается', async () => {
  const element = fakeMedia(125)
  const promise = mediaFileInfo(new File(['x'], 'встреча.mp4'), () => element)
  element.dispatchEvent(new Event('loadedmetadata'))
  await expect(promise).resolves.toEqual({ durationSec: 125, hasVideo: true })
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
})
