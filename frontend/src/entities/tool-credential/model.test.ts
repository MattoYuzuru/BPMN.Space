import {
  availableProviders,
  CAPABILITY,
  type CapabilityCard,
  CREDENTIAL_ERROR,
  type Credential,
  capabilityState,
  credentialErrorLabel,
  isExhausted,
  isUsable,
  kindLabel,
  monthlyLimitParts,
  monthlyLimitText,
  providerLabel,
  providersForKinds,
  providersText,
} from './model'

const card = (patch: Partial<CapabilityCard> = {}): CapabilityCard => ({
  capability: 'speech_to_text',
  label: 'Распознавание речи',
  description: 'Расшифровка записей',
  tool: 'transcribe',
  keys: 1,
  kinds: ['speech_to_text'],
  providers: [{ id: 'deepgram', label: 'Deepgram' }],
  available: true,
  last_error_code: null,
  ...patch,
})

const credential = (patch: Partial<Credential> = {}): Credential => ({
  id: 'c1',
  label: 'Рабочий',
  provider: 'deepgram',
  kinds: ['speech_to_text'],
  capabilities: ['speech_to_text'],
  priority: 100,
  enabled: true,
  is_default: false,
  base_url: null,
  default_model: null,
  key_hint: 'abcd',
  monthly_limit: null,
  exhausted_until: null,
  last_error: null,
  last_error_code: null,
  last_used_at: null,
  created_at: '2026-11-04T10:00:00Z',
  ...patch,
})

describe('ключи инструментов', () => {
  it('подписывает типы задач и возможности', () => {
    expect(kindLabel('speech_to_text')).toBe('Распознавание речи')
    expect(kindLabel('llm')).toBe('Модели')
    expect(CAPABILITY.ocr.label).toBe('Распознавание текста')
    expect(CAPABILITY.video_understanding.icon).toBe('video')
  })

  it('показывает понятную ошибку по коду и не теряет незнакомый', () => {
    expect(credentialErrorLabel('quota_exhausted')).toBe('Квота исчерпана')
    expect(CREDENTIAL_ERROR.auth?.tone).toBe('danger')
    expect(credentialErrorLabel('something_new')).toBe('Ошибка провайдера')
    expect(credentialErrorLabel(null)).toBeNull()
  })

  it('собирает провайдеров из карточек без повторов', () => {
    const providers = availableProviders([
      card(),
      card({
        capability: 'llm',
        providers: [
          { id: 'deepgram', label: 'Deepgram' },
          { id: 'anthropic', label: 'Anthropic' },
        ],
      }),
    ])
    expect(providers.map((provider) => provider.id)).toEqual(['anthropic', 'deepgram'])
    expect(providerLabel(providers, 'anthropic')).toBe('Anthropic')
    expect(providerLabel(providers, 'unknown')).toBe('unknown')
    expect(providersText([{ id: 'deepgram', label: 'Deepgram' }])).toBe('Deepgram')
  })

  it('ключ отдыхает после квоты и не считается рабочим, пока лимит не снят', () => {
    const now = new Date('2026-11-04T12:00:00Z')
    expect(isExhausted(credential({ exhausted_until: '2026-11-04T13:00:00Z' }), now)).toBe(true)
    expect(isExhausted(credential({ exhausted_until: '2026-11-04T10:00:00Z' }), now)).toBe(false)
    expect(isUsable(credential(), now)).toBe(true)
    expect(isUsable(credential({ enabled: false }), now)).toBe(false)
    expect(isUsable(credential({ exhausted_until: '2026-11-04T13:00:00Z' }), now)).toBe(false)
  })

  it('пишет лимиты на месяц словами', () => {
    expect(monthlyLimitParts(null)).toEqual([])
    expect(monthlyLimitParts({ minutes: 40 })[0]?.text).toBe('40\u00a0минут в месяц')
    expect(monthlyLimitText({ requests: 120 })).toBe('120\u00a0запросов в месяц')
    expect(monthlyLimitText({ minutes: 40, cost_usd: 5 })).toBe(
      '40\u00a0минут в месяц · $5 в месяц',
    )
  })

  it('оценивает состояние возможности для карточки', () => {
    expect(capabilityState(card())).toBe('ready')
    expect(capabilityState(card({ keys: 0 }))).toBe('empty')
    expect(capabilityState(card({ keys: 0, last_error_code: 'auth' }))).toBe('error')
  })
})

describe('провайдеры по типам задач', () => {
  it('Deepgram остаётся для распознавания, но не предлагается для моделей', () => {
    const capabilities: CapabilityCard[] = [
      card({ kinds: ['speech_to_text'], providers: [{ id: 'deepgram', label: 'Deepgram' }] }),
      card({
        capability: 'llm',
        kinds: ['llm'],
        providers: [
          { id: 'anthropic', label: 'Anthropic' },
          { id: 'openai', label: 'OpenAI' },
        ],
      }),
    ]
    expect(providersForKinds(capabilities, ['llm']).map((item) => item.id)).toEqual([
      'anthropic',
      'openai',
    ])
    expect(providersForKinds(capabilities, ['speech_to_text']).map((item) => item.id)).toEqual([
      'deepgram',
    ])
    expect(
      providersForKinds(capabilities, ['llm', 'speech_to_text']).map((item) => item.id),
    ).toEqual(['anthropic', 'deepgram', 'openai'])
  })
})
