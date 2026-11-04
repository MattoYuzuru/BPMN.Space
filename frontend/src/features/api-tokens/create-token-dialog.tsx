import { useState } from 'react'
import {
  API_SCOPES,
  type ApiScope,
  type ApiTokenCreated,
  DEFAULT_EXPIRY_DAYS,
  DEFAULT_SCOPES,
  EXPIRY_OPTIONS,
  mcpCommand,
  orderedScopes,
  useCreateApiToken,
  useTokenProjectChoices,
} from '@/entities/api-token'
import { errorMessage } from '@/shared/api/client'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Button,
  Card,
  Checkbox,
  CopyField,
  Dialog,
  DialogContent,
  Field,
  Icon,
  Input,
  RadioGroup,
  RadioGroupItem,
  ScrollArea,
  Select,
  Skeleton,
} from '@/shared/ui'

const FORM_ID = 'create-api-token-form'

type ProjectMode = 'all' | 'selected'

interface FormState {
  name: string
  scopes: ApiScope[]
  projectMode: ProjectMode
  projectIds: string[]
  days: string
}

const EMPTY: FormState = {
  name: '',
  scopes: DEFAULT_SCOPES,
  projectMode: 'all',
  projectIds: [],
  days: String(DEFAULT_EXPIRY_DAYS),
}

/**
 * Создание токена для агента. Секрет сервер отдаёт один раз: после создания окно показывает его
 * и готовую команду подключения, а при закрытии забывает.
 */
export function CreateTokenDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateApiToken()
  const [form, setForm] = useState<FormState>(EMPTY)
  const [error, setError] = useState<string>()
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)

  const close = (next: boolean) => {
    // Пока сервер создаёт токен, окно не закрывается (Esc, подложка, «Отмена»): иначе токен
    // появится на сервере, а его секрет, показываемый один раз, потеряется.
    if (!next && create.isPending) return
    if (!next) {
      setForm(EMPTY)
      setError(undefined)
      setCreated(null)
      create.reset()
    }
    onOpenChange(next)
  }

  const selectedEmpty = form.projectMode === 'selected' && form.projectIds.length === 0
  const canSubmit = form.name.trim().length > 0 && form.scopes.length > 0 && !selectedEmpty

  const submit = () => {
    setError(undefined)
    create.mutate(
      {
        name: form.name.trim(),
        scopes: orderedScopes(form.scopes),
        project_ids: form.projectMode === 'all' ? null : form.projectIds,
        expires_in_days: Number(form.days),
      },
      {
        onSuccess: (token) => {
          setCreated(token)
          // Тур по волнам 2–4 ждёт этот факт: токен реально создан на сервере.
          emitOnboardingSignal({ type: 'agent.token.created', id: token.id, name: token.name })
        },
        onError: (failure) => setError(errorMessage(failure)),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        size="lg"
        hideClose={create.isPending}
        title={created ? 'Токен создан' : 'Создать токен'}
        description={
          created
            ? 'Скопируйте токен сейчас: после закрытия окна показать его снова нельзя.'
            : 'Агент действует от вашего имени и только в пределах выбранных прав.'
        }
        footer={
          created ? (
            <Button variant="primary" autoFocus onClick={() => close(false)}>
              Готово
            </Button>
          ) : (
            <>
              <Button variant="ghost" disabled={create.isPending} onClick={() => close(false)}>
                Отмена
              </Button>
              <Button
                variant="primary"
                loading={create.isPending}
                disabled={!canSubmit}
                type="submit"
                form={FORM_ID}
              >
                Создать токен
              </Button>
            </>
          )
        }
      >
        {created ? (
          <CreatedToken token={created} />
        ) : (
          <form
            id={FORM_ID}
            className="flex flex-col gap-5"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              if (canSubmit) submit()
            }}
          >
            <Field label="Название" hint="Например, «Claude Code на ноутбуке»" error={error}>
              <Input
                name="token-name"
                autoComplete="off"
                maxLength={80}
                value={form.name}
                onChange={(event) => {
                  setError(undefined)
                  setForm({ ...form, name: event.target.value })
                }}
              />
            </Field>
            <ScopesField
              value={form.scopes}
              onChange={(scopes) => setForm((current) => ({ ...current, scopes }))}
            />
            <ProjectsField
              mode={form.projectMode}
              selected={form.projectIds}
              onModeChange={(projectMode) => setForm((current) => ({ ...current, projectMode }))}
              onSelectedChange={(projectIds) => setForm((current) => ({ ...current, projectIds }))}
            />
            <Field label="Срок действия">
              <Select
                options={EXPIRY_OPTIONS}
                value={form.days}
                onValueChange={(days) => setForm((current) => ({ ...current, days }))}
              />
            </Field>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

function ScopesField({
  value,
  onChange,
}: {
  value: ApiScope[]
  onChange: (scopes: ApiScope[]) => void
}) {
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="type-ui font-medium mb-2 text-fg">Права</legend>
      {API_SCOPES.map((scope) => (
        <Checkbox
          key={scope.value}
          label={scope.label}
          description={scope.description}
          checked={value.includes(scope.value)}
          onCheckedChange={(checked) =>
            onChange(
              checked === true
                ? orderedScopes([...value, scope.value])
                : value.filter((item) => item !== scope.value),
            )
          }
        />
      ))}
      {value.length === 0 && (
        <p className="type-caption text-danger-fg">Выберите хотя бы одно право.</p>
      )}
    </fieldset>
  )
}

function ProjectsField({
  mode,
  selected,
  onModeChange,
  onSelectedChange,
}: {
  mode: ProjectMode
  selected: string[]
  onModeChange: (mode: ProjectMode) => void
  onSelectedChange: (ids: string[]) => void
}) {
  const projects = useTokenProjectChoices()
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="type-ui font-medium mb-2 text-fg">Проекты</legend>
      <RadioGroup
        orientation="horizontal"
        value={mode}
        onValueChange={(next) => onModeChange(next as ProjectMode)}
        aria-label="Проекты"
      >
        <RadioGroupItem value="all" label="Все проекты" />
        <RadioGroupItem value="selected" label="Выбранные" />
      </RadioGroup>
      {mode === 'selected' && (
        <Card variant="sunken" padding="none">
          {projects.isPending && <Skeleton className="m-3 h-12" />}
          {projects.isError && (
            <p role="alert" className="type-ui p-3 text-danger-fg">
              Не удалось загрузить проекты.
            </p>
          )}
          {projects.data && projects.data.length === 0 && (
            <p className="type-ui p-3 text-fg-muted">Своих и общих проектов пока нет.</p>
          )}
          {projects.data && projects.data.length > 0 && (
            <ScrollArea className="max-h-48" viewportClassName="max-h-48">
              <div className="flex flex-col gap-2 p-3">
                {projects.data.map((project) => (
                  <Checkbox
                    key={project.id}
                    label={project.title}
                    checked={selected.includes(project.id)}
                    onCheckedChange={(checked) =>
                      onSelectedChange(
                        checked === true
                          ? [...selected, project.id]
                          : selected.filter((id) => id !== project.id),
                      )
                    }
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </Card>
      )}
    </fieldset>
  )
}

/** Секрет и команда подключения — единственный показ. */
function CreatedToken({ token }: { token: ApiTokenCreated }) {
  const commandText = mcpCommand(window.location.origin, token.secret)
  return (
    <div className="flex flex-col gap-4">
      <CopyField
        label="Токен"
        value={token.secret}
        copyMessage="Токен скопирован"
        copyLabel="Копировать токен"
        hint="Показывается один раз. Храните его как пароль."
        leadingIcon="key"
      />
      <div {...tourAnchor(TOUR_ANCHORS.agentCopyCommand)}>
        <CopyField
          label="Команда для Claude Code"
          value={commandText}
          copyMessage="Команда скопирована"
          copyLabel="Копировать команду"
          hint="Команда подключит MCP-сервер к Claude Code."
          multiline
          onCopied={() => emitOnboardingSignal({ type: 'agent.command.copied' })}
        />
      </div>
      <Card variant="sunken" padding="sm" className="flex items-start gap-2">
        <Icon name="info" size={16} className="mt-0.5 shrink-0 text-fg-subtle" />
        <p className="type-caption text-fg-muted">
          MCP-сервер работает по адресу <span className="font-mono">/mcp</span>: команда добавит его
          в Claude Code. Токен действует только в пределах выбранных прав, проектов и срока; REST
          API <span className="font-mono">/api/v1</span> тоже доступен в заголовке{' '}
          <span className="font-mono">Authorization: Bearer</span>.
        </p>
      </Card>
    </div>
  )
}
