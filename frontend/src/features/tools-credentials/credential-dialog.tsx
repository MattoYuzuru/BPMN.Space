import { useState } from 'react'
import {
  availableProviders,
  CAPABILITY,
  type CapabilityCard,
  CREDENTIAL_KIND,
  type Credential,
  type CredentialCapability,
  type CredentialKind,
  type CredentialProvider,
  PROVIDER_HINTS,
  PROVIDER_HINTS_DATE,
  useCreateToolCredential,
  useUpdateToolCredential,
} from '@/entities/tool-credential'
import { errorMessage } from '@/shared/api/client'
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  Divider,
  Field,
  Icon,
  Input,
  SecretInput,
  Select,
  Switch,
  Tag,
  toast,
} from '@/shared/ui'

const FORM_ID = 'credential-form'

/** Какие возможности закрывает тип задачи — для подсказок «где взять ключ». */
const KIND_CAPABILITIES: Record<CredentialKind, CredentialCapability[]> = {
  llm: ['llm'],
  speech_to_text: ['speech_to_text'],
  ocr: ['ocr'],
  vision: ['vision'],
  video: ['video_understanding'],
  web_search: ['web_search'],
  web_fetch: ['web_fetch'],
  tts: ['tts'],
}

const KINDS = Object.keys(CREDENTIAL_KIND) as CredentialKind[]

const FALLBACK_PROVIDERS: CredentialProvider[] = [
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'openai_compatible', label: 'Совместимый с OpenAI' },
  { id: 'deepgram', label: 'Deepgram' },
  { id: 'groq', label: 'Groq' },
]

function limitField(minutes: string, requests: string, cost: string) {
  const parsed = {
    minutes: Number.parseInt(minutes, 10),
    requests: Number.parseInt(requests, 10),
    cost_usd: Number.parseFloat(cost.replace(',', '.')),
  }
  const limit = {
    minutes: Number.isFinite(parsed.minutes) && parsed.minutes > 0 ? parsed.minutes : null,
    requests: Number.isFinite(parsed.requests) && parsed.requests > 0 ? parsed.requests : null,
    cost_usd: Number.isFinite(parsed.cost_usd) && parsed.cost_usd > 0 ? parsed.cost_usd : null,
  }
  return limit.minutes === null && limit.requests === null && limit.cost_usd === null ? null : limit
}

/**
 * Добавление и правка ключа инструмента (RFC-0006): типы задач, провайдер, приоритет,
 * лимит на месяц и подсказки «где взять ключ». Ключ показывается только при вводе.
 */
export function CredentialDialog({
  open,
  credential,
  capabilities,
  onOpenChange,
}: {
  open: boolean
  /** null — добавление; иначе правка без замены ключа. */
  credential: Credential | null
  capabilities: readonly CapabilityCard[]
  onOpenChange: (open: boolean) => void
}) {
  const editing = credential !== null
  const providers = availableProviders(capabilities)
  const options = providers.length > 0 ? providers : FALLBACK_PROVIDERS
  const create = useCreateToolCredential()
  const update = useUpdateToolCredential()
  const [kinds, setKinds] = useState<CredentialKind[]>(credential?.kinds ?? ['llm'])
  const [provider, setProvider] = useState(credential?.provider ?? options[0]?.id ?? 'anthropic')
  const [label, setLabel] = useState(credential?.label ?? '')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(credential?.base_url ?? '')
  const [defaultModel, setDefaultModel] = useState(credential?.default_model ?? '')
  const [priority, setPriority] = useState(String(credential?.priority ?? 100))
  const [enabled, setEnabled] = useState(credential?.enabled ?? true)
  const [isDefault, setIsDefault] = useState(credential?.is_default ?? false)
  const [minutes, setMinutes] = useState(String(credential?.monthly_limit?.minutes ?? ''))
  const [requests, setRequests] = useState(String(credential?.monthly_limit?.requests ?? ''))
  const [cost, setCost] = useState(
    credential?.monthly_limit?.cost_usd != null ? String(credential.monthly_limit.cost_usd) : '',
  )
  const [error, setError] = useState<string>()
  const pending = create.isPending || update.isPending
  const hasLlm = kinds.includes('llm')
  const compatible = provider === 'openai_compatible'
  const priorityValue = Number.parseInt(priority, 10)
  const valid =
    kinds.length > 0 &&
    (editing || (apiKey.trim().length > 0 && provider.length > 0)) &&
    (editing || !compatible || baseUrl.trim().length > 0) &&
    Number.isFinite(priorityValue) &&
    priorityValue >= 0

  const close = (next: boolean) => {
    if (!next && pending) return
    if (!next) {
      setError(undefined)
      onOpenChange(false)
    }
  }

  const submit = () => {
    setError(undefined)
    const limit = limitField(minutes, requests, cost)
    if (editing) {
      update.mutate(
        {
          id: credential.id,
          label: label.trim() || credential.label,
          default_model: defaultModel.trim() || null,
          priority: priorityValue,
          enabled,
          is_default: hasLlm ? isDefault : false,
          monthly_limit: limit,
          clear_monthly_limit: false,
        },
        {
          onSuccess: () => {
            toast.success('Ключ сохранён')
            onOpenChange(false)
          },
          onError: (failure) => setError(errorMessage(failure)),
        },
      )
      return
    }
    create.mutate(
      {
        kinds,
        provider,
        api_key: apiKey.trim(),
        label: label.trim() || null,
        base_url: compatible ? baseUrl.trim() : null,
        default_model: defaultModel.trim() || null,
        priority: priorityValue,
        enabled,
        is_default: hasLlm ? isDefault : false,
        monthly_limit: limit,
      },
      {
        onSuccess: () => {
          toast.success('Ключ добавлен')
          onOpenChange(false)
        },
        onError: (failure) => setError(errorMessage(failure)),
      },
    )
  }

  const hints = [...new Set(kinds.flatMap((kind) => KIND_CAPABILITIES[kind]))].flatMap(
    (capability) => PROVIDER_HINTS[capability],
  )
  const seenHints = new Set<string>()
  const uniqueHints = hints.filter((hint) => {
    const key = `${hint.provider}:${hint.url}`
    if (seenHints.has(key)) return false
    seenHints.add(key)
    return true
  })

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        size="lg"
        hideClose={pending}
        title={editing ? 'Ключ инструмента' : 'Добавить ключ инструмента'}
        description={
          editing
            ? 'Ключ и провайдер не меняются — только название, приоритет, лимит и включённость.'
            : 'Один ключ может закрывать несколько задач: например, ключ OpenAI — модели и распознавание речи.'
        }
        footer={
          <>
            <Button variant="ghost" disabled={pending} onClick={() => close(false)}>
              Отмена
            </Button>
            <Button
              variant="primary"
              type="submit"
              form={FORM_ID}
              loading={pending}
              disabled={!valid}
            >
              {editing ? 'Сохранить' : 'Проверить и сохранить'}
            </Button>
          </>
        }
      >
        <form
          id={FORM_ID}
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            if (valid) submit()
          }}
        >
          {editing ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="type-label w-full text-fg-muted">Типы задач</span>
              {credential.kinds.map((kind) => (
                <Tag key={kind} icon={CREDENTIAL_KIND[kind].icon}>
                  {CREDENTIAL_KIND[kind].label}
                </Tag>
              ))}
              <span className="type-caption text-fg-subtle">
                Типы задач у ключа не меняются: удалите ключ и добавьте новый.
              </span>
            </div>
          ) : (
            <fieldset className="flex flex-col gap-2">
              <legend className="type-label mb-1 text-fg">Типы задач</legend>
              {KINDS.map((kind) => (
                <Checkbox
                  key={kind}
                  label={CREDENTIAL_KIND[kind].label}
                  description={CAPABILITY[KIND_CAPABILITIES[kind][0] ?? 'llm']?.description}
                  checked={kinds.includes(kind)}
                  onCheckedChange={(checked) =>
                    setKinds((current) =>
                      checked === true
                        ? KINDS.filter((item) => current.includes(item) || item === kind)
                        : current.filter((item) => item !== kind),
                    )
                  }
                />
              ))}
              {kinds.length === 0 && (
                <p className="type-caption text-danger-fg">Выберите хотя бы один тип задач.</p>
              )}
            </fieldset>
          )}

          {!editing && (
            <Field label="Провайдер">
              <Select
                aria-label="Провайдер"
                value={provider}
                onValueChange={setProvider}
                options={options.map((item) => ({ value: item.id, label: item.label }))}
              />
            </Field>
          )}

          <Field label="Название" hint="Необязательно: «Рабочий», «Личный»">
            <Input
              name="label"
              autoComplete="off"
              maxLength={60}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </Field>

          {!editing && (
            <Field
              label="Ключ"
              hint="Проверяется у провайдера и хранится зашифрованным"
              error={error}
            >
              <SecretInput
                value={apiKey}
                autoFocus
                onChange={(event) => {
                  setError(undefined)
                  setApiKey(event.target.value)
                }}
              />
            </Field>
          )}
          {!editing && compatible && (
            <Field label="Адрес API" hint="Например, https://openrouter.ai/api/v1">
              <Input
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                leadingIcon="route"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </Field>
          )}

          <div className="grid grid-cols-2 gap-3">
            <Field label="Приоритет" hint="Меньше — раньше в переборе">
              <Input
                inputMode="numeric"
                value={priority}
                onChange={(event) => setPriority(event.target.value)}
              />
            </Field>
            <Field label="Модель по умолчанию" optional hint="Для ключей моделей">
              <Input
                autoComplete="off"
                value={defaultModel}
                placeholder="Например, claude-opus-5-5"
                onChange={(event) => setDefaultModel(event.target.value)}
              />
            </Field>
          </div>

          <fieldset className="flex flex-col gap-3">
            <legend className="type-label mb-1 text-fg">Лимит на месяц</legend>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Минуты" optional>
                <Input
                  inputMode="numeric"
                  value={minutes}
                  onChange={(event) => setMinutes(event.target.value)}
                />
              </Field>
              <Field label="Запросы" optional>
                <Input
                  inputMode="numeric"
                  value={requests}
                  onChange={(event) => setRequests(event.target.value)}
                />
              </Field>
              <Field label="Доллары" optional>
                <Input
                  inputMode="decimal"
                  value={cost}
                  onChange={(event) => setCost(event.target.value)}
                />
              </Field>
            </div>
            <p className="type-caption text-fg-muted">
              Когда лимит закончится, ключ отдохнёт и снова включится: прогон спросит, что делать.
            </p>
          </fieldset>

          <div className="flex flex-wrap items-center gap-4">
            <Switch label="Ключ включён" checked={enabled} onCheckedChange={setEnabled} />
            {hasLlm && (
              <Switch
                label="Модель по умолчанию"
                checked={isDefault}
                disabled={credential?.is_default ?? false}
                onCheckedChange={setIsDefault}
              />
            )}
          </div>

          {uniqueHints.length > 0 && (
            <>
              <Divider />
              <div className="flex flex-col gap-1.5">
                <span className="type-label text-fg">Где взять ключ</span>
                <ul className="flex flex-col gap-1">
                  {uniqueHints.slice(0, 6).map((hint) => (
                    <li key={`${hint.provider}:${hint.url}`}>
                      <a
                        href={hint.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 type-caption text-accent-fg hover:underline"
                      >
                        {hint.provider}
                        {hint.note ? ` \u00B7 ${hint.note}` : ''}
                        <Icon name="external-link" size={14} />
                      </a>
                    </li>
                  ))}
                </ul>
                <span className="type-caption text-fg-subtle">
                  Сверено {PROVIDER_HINTS_DATE}. Полный каталог провайдеров появится отдельной
                  задачей.
                </span>
              </div>
            </>
          )}
        </form>
      </DialogContent>
    </Dialog>
  )
}
