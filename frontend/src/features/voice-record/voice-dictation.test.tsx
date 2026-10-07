import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ApiError } from '@/shared/api/client'
import { Textarea, TooltipProvider, toast } from '@/shared/ui'
import { NO_SPEECH_MESSAGE, transcribeAudio } from './api'
import type { RecorderState } from './use-voice-recorder'
import { VoiceCapture } from './voice-capture'
import { appendDictation, VoiceDictation } from './voice-dictation'

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  transcribeAudio: vi.fn(),
  useTranscribe: () => useMutation({ mutationFn: (blob: Blob) => transcribeAudio(blob) }),
}))

vi.mock('./use-voice-recorder', async () => {
  const { useCallback, useState } = await import('react')
  return {
    useVoiceRecorder: () => {
      const [state, setState] = useState<RecorderState>({ status: 'idle' })
      return {
        state,
        levels: [0.2, 0.5, 0.8],
        elapsed: 2,
        start: useCallback(async () => setState({ status: 'recording' }), []),
        stop: useCallback(
          () => setState({ status: 'recorded', blob: new Blob(['speech']), durationSec: 2 }),
          [],
        ),
        cancel: useCallback(() => setState({ status: 'idle' }), []),
      }
    },
  }
})

function mount(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>,
  )
}

function Draft({ onSubmit }: { onSubmit: (text: string) => void }) {
  const [text, setText] = useState('Исходный ответ')
  return (
    <VoiceDictation
      onText={(result) => setText((draft) => appendDictation(draft, result))}
      onSubmit={(result) => onSubmit(appendDictation(text, result))}
    >
      <Textarea aria-label="Ответ" value={text} onChange={(event) => setText(event.target.value)} />
    </VoiceDictation>
  )
}

function deferredTranscript() {
  let resolve!: (value: Awaited<ReturnType<typeof transcribeAudio>>) => void
  const promise = new Promise<Awaited<ReturnType<typeof transcribeAudio>>>((done) => {
    resolve = done
  })
  vi.mocked(transcribeAudio).mockReturnValue(promise)
  return { resolve: () => resolve({ text: 'Распознанный ответ', duration_sec: 2, language: 'ru' }) }
}

describe('диктовка внутри текстового поля', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(transcribeAudio).mockResolvedValue({
      text: 'Распознанный ответ',
      duration_sec: 2,
      language: 'ru',
    })
  })

  afterEach(() => vi.restoreAllMocks())

  it('остановка дополняет черновик и возвращает фокус в поле, не отправляя ответ', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    mount(<Draft onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Надиктовать' }))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Идёт запись')
    await user.click(screen.getByRole('button', { name: 'Остановить и вставить текст' }))
    const field = await screen.findByRole('textbox', { name: 'Ответ' })
    expect(field).toHaveValue('Исходный ответ\nРаспознанный ответ')
    expect(field).toHaveFocus()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(transcribeAudio).toHaveBeenCalledOnce()
  })

  it('стрелка распознаёт и один раз отправляет весь ответ вместе с черновиком', async () => {
    const user = userEvent.setup()
    const request = deferredTranscript()
    const onSubmit = vi.fn()
    mount(<Draft onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Надиктовать' }))
    await user.click(screen.getByRole('button', { name: 'Распознать и отправить ответ' }))
    expect(screen.getByRole('status')).toHaveTextContent('Распознаю речь')
    expect(screen.getByRole('button', { name: 'Распознать и отправить ответ' })).toBeDisabled()
    await act(async () => request.resolve())
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Исходный ответ\nРаспознанный ответ'),
    )
  })

  it('Escape отменяет распознавание и игнорирует его поздний ответ', async () => {
    const user = userEvent.setup()
    const request = deferredTranscript()
    const onSubmit = vi.fn()
    mount(<Draft onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Надиктовать' }))
    await user.click(screen.getByRole('button', { name: 'Распознать и отправить ответ' }))
    const signal = vi.mocked(transcribeAudio).mock.calls[0]?.[1]
    await user.keyboard('{Escape}')
    expect(signal?.aborted).toBe(true)
    expect(screen.getByRole('textbox')).toHaveValue('Исходный ответ')
    await act(async () => request.resolve())
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('Исходный ответ')
  })

  it('тишина показывает уведомление и сохраняет черновик', async () => {
    const user = userEvent.setup()
    const warning = vi.spyOn(toast, 'warning').mockReturnValue('warning')
    vi.mocked(transcribeAudio).mockRejectedValue(
      new ApiError(422, NO_SPEECH_MESSAGE, { code: 'NO_SPEECH' }),
    )
    const onSubmit = vi.fn()
    mount(<Draft onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Надиктовать' }))
    await user.click(screen.getByRole('button', { name: 'Распознать и отправить ответ' }))
    await screen.findByRole('textbox')
    expect(warning).toHaveBeenCalledWith('Речь не распознана', { description: NO_SPEECH_MESSAGE })
    expect(screen.getByRole('textbox')).toHaveValue('Исходный ответ')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('закрытие формы отменяет текущую транскрибацию', async () => {
    const user = userEvent.setup()
    const request = deferredTranscript()
    const onSubmit = vi.fn()
    const view = mount(<Draft onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Надиктовать' }))
    await user.click(screen.getByRole('button', { name: 'Распознать и отправить ответ' }))
    const signal = vi.mocked(transcribeAudio).mock.calls[0]?.[1]
    view.unmount()
    expect(signal?.aborted).toBe(true)
    await act(async () => request.resolve())
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('тишина в голосовом источнике тоже показывает toast и позволяет записать заново', async () => {
    const user = userEvent.setup()
    const warning = vi.spyOn(toast, 'warning').mockReturnValue('warning')
    vi.mocked(transcribeAudio).mockRejectedValue(
      new ApiError(422, NO_SPEECH_MESSAGE, { code: 'NO_SPEECH' }),
    )
    mount(<VoiceCapture submitLabel="Добавить источник" onSubmit={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Начать запись' }))
    await user.click(screen.getByRole('button', { name: 'Остановить' }))
    await waitFor(() => expect(warning).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: 'Начать запись' })).toBeEnabled()
    expect(screen.queryByText(/Ошибка сервера/)).not.toBeInTheDocument()
  })
})
