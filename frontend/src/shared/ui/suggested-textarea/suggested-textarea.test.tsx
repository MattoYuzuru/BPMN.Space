import { act, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderUi } from '@/test/render'
import {
  SUGGESTION_PREVIEW_CHARS,
  SuggestedTextarea,
  suggestionPreview,
} from './suggested-textarea'

const SUGGESTION =
  'Заявитель подаёт заявку на подключение гаража к электросети через личный кабинет. Специалист проверяет заявку и документы.'

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => {
  vi.useRealTimers()
})

function Harness({
  suggestion = SUGGESTION,
  onInsert,
  onDismiss,
  initial = '',
}: {
  suggestion?: string | null
  onInsert?: (text: string) => void
  onDismiss?: () => void
  initial?: string
}) {
  const [value, setValue] = useState(initial)
  return (
    <SuggestedTextarea
      aria-label="Текст"
      value={value}
      onValueChange={setValue}
      suggestion={suggestion}
      onInsert={onInsert}
      onDismiss={onDismiss}
      placeholder="Вставьте описание"
    />
  )
}

const field = () => screen.getByRole('textbox', { name: 'Текст' }) as HTMLTextAreaElement

describe('suggestionPreview', () => {
  it('короткий текст — как есть, длинный — до 140 символов по слову и с многоточием', () => {
    expect(suggestionPreview('Коротко.')).toBe('Коротко.')
    const long = 'слово '.repeat(60)
    const preview = suggestionPreview(long)
    expect(preview.endsWith('…')).toBe(true)
    expect(preview.length).toBeLessThanOrEqual(SUGGESTION_PREVIEW_CHARS + 1)
    expect(preview.endsWith(' …')).toBe(false)
  })
})

describe('SuggestedTextarea', () => {
  it('в пустом поле — призрак начала подсказки и две кнопки', () => {
    renderUi(<Harness />)
    expect(field()).toHaveAttribute('placeholder', suggestionPreview(SUGGESTION))
    expect(field()).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Вставить' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Напишу сам' })).toBeInTheDocument()
  })

  it('без подсказки — обычное поле: свой placeholder, кнопок нет', () => {
    renderUi(<Harness suggestion={null} />)
    expect(field()).toHaveAttribute('placeholder', 'Вставьте описание')
    expect(screen.queryByRole('button', { name: 'Вставить' })).toBeNull()
  })

  it('«Вставить» впечатывает текст постепенно (~120 символов в секунду) и отдаёт поле', async () => {
    const onInsert = vi.fn()
    const { user } = renderUi(<Harness onInsert={onInsert} />)
    await user.click(screen.getByRole('button', { name: 'Вставить' }))
    expect(onInsert).toHaveBeenCalledWith(SUGGESTION)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250)
    })
    const partial = field().value
    expect(partial.length).toBeGreaterThan(5)
    expect(partial.length).toBeLessThan(SUGGESTION.length)
    expect(SUGGESTION.startsWith(partial)).toBe(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(field()).toHaveValue(SUGGESTION)
    expect(screen.queryByRole('button', { name: 'Вставить' })).toBeNull()
  })

  it('Tab в пустом поле — то же, что «Вставить»', async () => {
    const { user } = renderUi(<Harness />)
    field().focus()
    await user.keyboard('{Tab}')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(field()).toHaveValue(SUGGESTION)
  })

  it('клавиша во время печати допечатывает остаток сразу, а символ не вставляется', async () => {
    const { user } = renderUi(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Вставить' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150)
    })
    expect(field().value.length).toBeLessThan(SUGGESTION.length)
    field().focus()
    await user.keyboard('я')
    expect(field()).toHaveValue(SUGGESTION)
    // Управление у человека: дальше печатает он.
    await user.keyboard('!')
    expect(field()).toHaveValue(`${SUGGESTION}!`)
  })

  it('«Напишу сам» закрывает подсказку, свой ввод закрывает её тоже', async () => {
    const onDismiss = vi.fn()
    const { user } = renderUi(<Harness onDismiss={onDismiss} />)
    await user.click(screen.getByRole('button', { name: 'Напишу сам' }))
    expect(onDismiss).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: 'Вставить' })).toBeNull()
    expect(field()).toHaveAttribute('placeholder', 'Вставьте описание')
  })

  it('собственный ввод убирает подсказку', async () => {
    const onDismiss = vi.fn()
    const { user } = renderUi(<Harness onDismiss={onDismiss} />)
    field().focus()
    await user.keyboard('Свой текст')
    expect(field()).toHaveValue('Свой текст')
    expect(onDismiss).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: 'Вставить' })).toBeNull()
  })

  it('в непустом поле подсказки нет', () => {
    renderUi(<Harness initial="Уже написано" />)
    expect(screen.queryByRole('button', { name: 'Вставить' })).toBeNull()
  })
})
