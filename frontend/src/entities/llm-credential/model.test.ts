import {
  capabilitySummary,
  choiceLabel,
  choiceRequest,
  effectiveEffort,
  effortOptions,
  keyMask,
  type LlmCredential,
  type ModelCapabilities,
  modelLabel,
  resolveChoice,
} from './model'

function caps(overrides: Partial<ModelCapabilities> = {}): ModelCapabilities {
  return {
    known: true,
    context_tokens: 1_000_000,
    max_output_tokens: 128_000,
    vision: true,
    pdf_input: true,
    tools: true,
    effort_levels: ['low', 'medium', 'high', 'max'],
    effort_default: 'medium',
    accepts_temperature: false,
    prices: null,
    ...overrides,
  }
}

function credential(overrides: Partial<LlmCredential> = {}): LlmCredential {
  return {
    id: 'c1',
    provider: 'anthropic',
    label: 'Рабочий',
    base_url: null,
    key_hint: 'abcd',
    default_model: 'claude-opus-5-5',
    is_default: true,
    created_at: '2026-11-01T00:00:00Z',
    last_used_at: null,
    last_error: null,
    ...overrides,
  }
}

describe('модель ключей', () => {
  it('подписывает модели Claude по-человечески, остальные оставляет как есть', () => {
    expect(modelLabel('claude-opus-5-5')).toBe('Claude Opus 5.5')
    expect(modelLabel('claude-fable-5-1')).toBe('Claude Fable 5.1')
    expect(modelLabel('gpt-4o')).toBe('gpt-4o')
  })

  it('маска показывает только подсказку, а не ключ', () => {
    expect(keyMask('abcd')).toBe('••••abcd')
    expect(keyMask('')).toBe('••••')
  })

  it('без явного выбора берёт ключ по умолчанию, без ключей — сервер', () => {
    const list = [credential()]
    expect(choiceLabel(list, null)).toBe('Claude Opus 5.5 · ключ «Рабочий»')
    expect(choiceLabel([], null)).toBe('Сервер по умолчанию')
    expect(resolveChoice([credential({ is_default: false })], null)).toBeNull()
  })

  it('явный выбор главнее ключа по умолчанию; удалённый ключ игнорируется', () => {
    const list = [credential(), credential({ id: 'c2', label: 'Личный', is_default: false })]
    expect(choiceLabel(list, { credentialId: 'c2', model: 'gpt-4o' })).toBe(
      'gpt-4o · ключ «Личный»',
    )
    expect(resolveChoice(list, { credentialId: 'gone', model: 'x' })?.credential.id).toBe('c1')
  })

  it('уровень работы: выбранный, если модель его умеет, иначе умолчание модели', () => {
    expect(effortOptions(caps()).map((item) => item.label)).toEqual([
      'Быстро',
      'Обычно',
      'Тщательно',
      'Максимум',
    ])
    // «Очень тщательно» показывается только у моделей, которые его поддерживают.
    expect(
      effortOptions(caps({ effort_levels: ['low', 'medium', 'high', 'xhigh', 'max'] })).map(
        (item) => item.value,
      ),
    ).toContain('xhigh')
    expect(effectiveEffort('high', caps())).toBe('high')
    expect(effectiveEffort('xhigh', caps())).toBe('medium')
    expect(effectiveEffort(undefined, caps())).toBe('medium')
    expect(effectiveEffort('high', caps({ effort_levels: [], effort_default: null }))).toBeNull()
    expect(effectiveEffort('high', undefined)).toBeNull()
  })

  it('метка показывает модель и уровень, если модель рассуждает', () => {
    const list = [credential()]
    const choice = { credentialId: 'c1', model: 'claude-opus-5-5', effort: 'high' as const }
    expect(choiceLabel(list, choice, caps())).toBe('Claude Opus 5.5 · тщательно · ключ «Рабочий»')
    expect(choiceLabel(list, null, caps())).toBe('Claude Opus 5.5 · обычно · ключ «Рабочий»')
    expect(choiceLabel(list, choice)).toBe('Claude Opus 5.5 · ключ «Рабочий»')
  })

  it('кратко описывает возможности модели', () => {
    const summary = capabilitySummary(
      caps({
        prices: {
          input: 4,
          output: 20,
          cache_read: 0.2,
          cache_write: 5,
          currency: 'USD',
          checked_on: '2026-10-06',
          note: null,
        },
      }),
    )
    expect(summary[0]).toBe('окно 1\u00A0млн токенов')
    expect(summary[1]).toBe('ответ до 128\u00A0тыс. токенов')
    expect(summary).toContain('изображения и PDF')
    expect(summary).toContain('уровни от «быстро» до «максимум»')
    expect(summary.at(-1)).toMatch(/^\$4 \/ \$20 за 1 млн токенов, цены на 6 октября/)
    expect(
      capabilitySummary(
        caps({
          known: false,
          context_tokens: null,
          max_output_tokens: null,
          vision: false,
          effort_levels: [],
        }),
      ),
    ).toEqual(['возможности модели неизвестны'])
  })

  it('поля запроса есть только при явном выборе', () => {
    expect(choiceRequest(null)).toEqual({})
    expect(choiceRequest({ credentialId: 'c2', model: 'gpt-4o' })).toEqual({
      credential_id: 'c2',
      model: 'gpt-4o',
    })
    expect(choiceRequest({ credentialId: 'c2', model: 'o3', effort: 'high' })).toEqual({
      credential_id: 'c2',
      model: 'o3',
      profile: { effort: 'high' },
    })
  })
})
