import {
  choiceLabel,
  choiceRequest,
  keyMask,
  type LlmCredential,
  modelLabel,
  resolveChoice,
} from './model'

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

  it('поля запроса есть только при явном выборе', () => {
    expect(choiceRequest(null)).toEqual({})
    expect(choiceRequest({ credentialId: 'c2', model: 'gpt-4o' })).toEqual({
      credential_id: 'c2',
      model: 'gpt-4o',
    })
  })
})
