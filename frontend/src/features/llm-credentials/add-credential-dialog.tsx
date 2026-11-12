import { useState } from 'react'
import {
  type LlmCredential,
  type LlmProvider,
  PROVIDERS,
  useCreateLlmCredential,
  useUpdateLlmCredential,
  WIRE_API_HINT,
  WIRE_APIS,
  type WireApi,
} from '@/entities/llm-credential'
import { errorMessage } from '@/shared/api/client'
import {
  Button,
  Dialog,
  DialogContent,
  Field,
  Input,
  SegmentedControl,
  Select,
  toast,
} from '@/shared/ui'
import { KeyField } from './key-field'
import { ModelSelect } from './model-select'

const FORM_ID = 'add-credential-form'
const EMPTY = {
  provider: 'anthropic' as LlmProvider,
  label: '',
  baseUrl: '',
  wireApi: 'chat_completions' as WireApi,
  apiKey: '',
}

/**
 * Добавление ключа в два шага: ключ (сервер проверяет его у провайдера) и модель по умолчанию из
 * списка этого аккаунта. Открытый ключ живёт только в поле формы и уходит одним запросом.
 */
export function AddCredentialDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateLlmCredential()
  const update = useUpdateLlmCredential()
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState<string>()
  const [created, setCreated] = useState<LlmCredential | null>(null)
  const [model, setModel] = useState<string | null>(null)

  const close = (next: boolean) => {
    if (!next) {
      setForm(EMPTY)
      setError(undefined)
      setCreated(null)
      setModel(null)
    }
    onOpenChange(next)
  }

  const compatible = form.provider === 'openai_compatible'
  const canSubmit = form.apiKey.trim().length > 0 && (!compatible || form.baseUrl.trim().length > 0)

  const submit = () => {
    setError(undefined)
    create.mutate(
      {
        provider: form.provider,
        api_key: form.apiKey.trim(),
        label: form.label.trim() || null,
        base_url: compatible ? form.baseUrl.trim() : null,
        wire_api: compatible ? form.wireApi : null,
        is_default: false,
      },
      {
        onSuccess: (credential) => {
          // Ключ больше не нужен на клиенте: стираем его из состояния сразу.
          setForm((current) => ({ ...current, apiKey: '' }))
          setCreated(credential)
          setModel(credential.default_model)
        },
        onError: (failure) => setError(errorMessage(failure)),
      },
    )
  }

  const finish = () => {
    if (!created) return
    const done = () => {
      toast.success('Ключ добавлен')
      close(false)
    }
    if (model && model !== created.default_model) {
      update.mutate({ id: created.id, default_model: model }, { onSuccess: done })
    } else done()
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        title={created ? 'Выберите модель' : 'Добавить ключ'}
        description={
          created
            ? 'Эта модель будет использоваться по умолчанию. Её можно сменить при запуске.'
            : 'Ключ проверяется у провайдера и хранится зашифрованным. Показать его снова нельзя.'
        }
        footer={
          created ? (
            // Прежнее поле формы исчезло: фокус переводим на кнопку, а не теряем.
            <Button variant="primary" autoFocus loading={update.isPending} onClick={finish}>
              Готово
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => close(false)}>
                Отмена
              </Button>
              <Button
                variant="primary"
                loading={create.isPending}
                disabled={!canSubmit}
                type="submit"
                form={FORM_ID}
              >
                Проверить и сохранить
              </Button>
            </>
          )
        }
      >
        {created ? (
          <ModelSelect credential={created} value={model} onChange={setModel} />
        ) : (
          <form
            id={FORM_ID}
            className="flex flex-col gap-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              if (canSubmit) submit()
            }}
          >
            <SegmentedControl<LlmProvider>
              aria-label="Провайдер"
              value={form.provider}
              onValueChange={(provider) => {
                setError(undefined)
                setForm((current) => ({ ...current, provider }))
              }}
              options={PROVIDERS}
            />
            <Field label="Название" hint="Необязательно: «Рабочий», «Личный»">
              <Input
                name="label"
                autoComplete="off"
                maxLength={60}
                value={form.label}
                onChange={(event) => setForm({ ...form, label: event.target.value })}
              />
            </Field>
            {compatible && (
              <Field label="Адрес API" hint="Например, https://openrouter.ai/api/v1">
                <Input
                  name="base-url"
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  leadingIcon="route"
                  value={form.baseUrl}
                  onChange={(event) => setForm({ ...form, baseUrl: event.target.value })}
                />
              </Field>
            )}
            {compatible && (
              <Field label="Протокол API" hint={WIRE_API_HINT}>
                <Select
                  aria-label="Протокол API"
                  value={form.wireApi}
                  onValueChange={(value) =>
                    setForm((current) => ({ ...current, wireApi: value as WireApi }))
                  }
                  options={WIRE_APIS}
                />
              </Field>
            )}
            <KeyField
              value={form.apiKey}
              onChange={(apiKey) => {
                setError(undefined)
                setForm((current) => ({ ...current, apiKey }))
              }}
              error={error}
            />
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
