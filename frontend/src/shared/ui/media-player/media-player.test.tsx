import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { createRef } from 'react'
import { TooltipProvider } from '@/shared/ui'
import { renderUi } from '@/test/render'
import { MediaPlayer, type MediaPlayerHandle } from './media-player'

// jsdom не умеет воспроизведение: подменяем методы и метаданные.
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
})

afterEach(() => vi.restoreAllMocks())

function loaded(duration = 120) {
  const element = screen.getByLabelText('Совещание 12.10')
  Object.defineProperty(element, 'duration', { configurable: true, value: duration })
  fireEvent.loadedMetadata(element)
  return element as HTMLMediaElement
}

describe('MediaPlayer', () => {
  it('играет, ставит паузу и показывает время', async () => {
    const { user } = renderUi(
      <MediaPlayer src="/sources/s1/media" kind="audio" label="Совещание 12.10" />,
    )
    const audio = loaded()
    expect(screen.getByText('0:00 / 2:00')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Слушать' }))
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Пауза' })).toHaveAttribute('aria-pressed', 'true')
    act(() => {
      audio.currentTime = 30
      fireEvent.timeUpdate(audio)
    })
    expect(screen.getByText('0:30 / 2:00')).toBeInTheDocument()
  })

  it('перематывает через Slider и императивный handle, подсвечивает время', async () => {
    const onSeek = vi.fn()
    const onTimeUpdate = vi.fn()
    const ref = createRef<MediaPlayerHandle>()
    const { user } = renderUi(
      <MediaPlayer
        ref={ref}
        src="/sources/s1/media"
        kind="audio"
        label="Совещание 12.10"
        onSeek={onSeek}
        onTimeUpdate={onTimeUpdate}
      />,
    )
    loaded()
    const slider = screen.getByRole('slider', { name: 'Позиция записи' })
    slider.focus()
    await user.keyboard('{Home}')
    await user.keyboard('{ArrowRight}')
    expect(onSeek).toHaveBeenCalled()
    act(() => ref.current?.seek(42))
    expect(onSeek).toHaveBeenLastCalledWith(42)
    expect(ref.current?.currentTime()).toBe(42)
    expect(screen.getByText('0:42 / 2:00')).toBeInTheDocument()
  })

  it('ошибку загрузки показывает спокойно и позволяет повторить', async () => {
    renderUi(<MediaPlayer src="/sources/s1/media" kind="video" label="Совещание 12.10" />)
    const video = screen.getByLabelText('Совещание 12.10')
    fireEvent.error(video)
    expect(screen.getByRole('alert')).toHaveTextContent('Запись не загрузилась')
    expect(
      within(screen.getByRole('alert')).getByRole('button', { name: /Повторить/ }),
    ).toBeInTheDocument()
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: /Повторить/ }))
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

it('перемотка до loadedmetadata применяется после метаданных, опрос длительности не сбрасывает плеер', () => {
  const onSeek = vi.fn()
  const ref = createRef<MediaPlayerHandle>()
  const view = renderUi(
    <MediaPlayer
      ref={ref}
      src="/sources/s1/media"
      kind="audio"
      label="Совещание 12.10"
      durationSec={0}
      onSeek={onSeek}
    />,
  )
  const audio = screen.getByLabelText('Совещание 12.10')
  act(() => ref.current?.seek(42))
  expect(onSeek).toHaveBeenLastCalledWith(42)
  expect(screen.getByText('0:42 / 0:00')).toBeInTheDocument()
  Object.defineProperty(audio, 'duration', { configurable: true, value: 120 })
  fireEvent.loadedMetadata(audio)
  expect(screen.getByText('0:42 / 2:00')).toBeInTheDocument()
  expect(screen.queryByText(/Загрузка записи/)).toBeNull()
  // Опрос проекта приносит ту же длительность — плеер не должен снова «загружаться».
  view.rerender(
    <TooltipProvider>
      <MediaPlayer
        ref={ref}
        src="/sources/s1/media"
        kind="audio"
        label="Совещание 12.10"
        durationSec={120}
        onSeek={onSeek}
      />
    </TooltipProvider>,
  )
  expect(screen.queryByText(/Загрузка записи/)).toBeNull()
  act(() => ref.current?.seek(30))
  expect(screen.getByText('0:30 / 2:00')).toBeInTheDocument()
})

it('AbortError от play() не считается ошибкой загрузки', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
    Object.assign(new Error('play interrupted'), { name: 'AbortError' }),
  )
  const { user } = renderUi(
    <MediaPlayer src="/sources/s1/media" kind="audio" label="Совещание 12.10" />,
  )
  await user.click(screen.getByRole('button', { name: 'Слушать' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(screen.queryByText(/не загрузилась/)).toBeNull()
})
