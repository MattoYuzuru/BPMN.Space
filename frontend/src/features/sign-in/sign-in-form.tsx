import { useRouter } from '@tanstack/react-router'
import { type FormEvent, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import {
  type AuthFormError,
  type AuthMode,
  authFormError,
  useLogin,
  useRegister,
  validateAuthForm,
} from '@/entities/session'
import { generatePassword } from '@/shared/lib/password'
import { Button, Field, IconButton, Input, SegmentedControl, toast } from '@/shared/ui'

const MODES = [
  { value: 'login' as const, label: 'Вход' },
  { value: 'register' as const, label: 'Регистрация' },
]

/**
 * Правила пароля для Safari / iCloud Keychain: он генерирует пароль под них. Атрибута нет в типах
 * React, поэтому передаём через типизированный spread. Совпадает с проверкой на сервере (12–128).
 */
const SAFARI_PASSWORD_RULES: Record<string, string> = {
  passwordrules:
    'minlength: 12; maxlength: 128; required: lower; required: upper; required: digit;',
}

export interface SignInFormProps {
  mode: AuthMode
  onModeChange: (mode: AuthMode) => void
  /** Куда перейти после входа (уже проверенный путь этого же сайта). */
  redirectTo: string
}

/**
 * Вход и регистрация в одной форме. Ошибки показываются под полем, к которому относятся;
 * общие (нет связи, слишком много попыток) — спокойным уведомлением. Enter отправляет форму.
 */
export function SignInForm({ mode, onModeChange, redirectTo }: SignInFormProps) {
  const router = useRouter()
  const login = useLogin()
  const register = useRegister()
  const submitting = login.isPending || register.isPending
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const passwordRef = useRef<HTMLInputElement>(null)
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({})

  const fail = (error: unknown) => {
    const result: AuthFormError = authFormError(error, mode)
    if (result.field === 'form') toast.error(result.message)
    else setErrors({ [result.field]: result.message })
  }

  /** Пароль создаётся и показывается в поле, копируется в буфер; сам он никуда больше не уходит. */
  const generate = async () => {
    const next = generatePassword()
    setPassword(next)
    setErrors((current) => ({ ...current, password: undefined }))
    setVisible(true)
    passwordRef.current?.focus()
    try {
      await navigator.clipboard.writeText(next)
      toast.success('Пароль скопирован', { description: 'Сохраните его в менеджере паролей' })
    } catch {
      toast('Пароль создан', { description: 'Скопируйте его из поля' })
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // Менеджер паролей предлагает сохранить пароль, только если на отправке поле — type="password".
    flushSync(() => setVisible(false))
    const found = validateAuthForm(mode, { email, password })
    setErrors(found)
    if (found.email || found.password) return
    const credentials = { email: email.trim(), password }
    const mutation = mode === 'login' ? login : register
    mutation.mutate(credentials, {
      onSuccess: () => void router.navigate({ href: redirectTo, replace: true }),
      onError: fail,
    })
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-5">
      <SegmentedControl<AuthMode>
        aria-label="Вход или регистрация"
        value={mode}
        onValueChange={(next) => {
          setErrors({})
          setVisible(false)
          onModeChange(next)
        }}
        options={MODES}
        className="self-center"
      />
      <div className="flex flex-col gap-4">
        <Field label="Почта" error={errors.email}>
          <Input
            autoFocus
            name="email"
            type="email"
            inputMode="email"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            leadingIcon="mail"
            value={email}
            placeholder="name@company.ru"
            onChange={(event) => {
              setEmail(event.target.value)
              if (errors.email) setErrors((current) => ({ ...current, email: undefined }))
            }}
          />
        </Field>
        <Field
          // Поле пересоздаётся при смене режима: браузер заново классифицирует его как
          // current-password или new-password (смену атрибута у того же элемента Chrome замечает плохо).
          key={mode}
          label="Пароль"
          error={errors.password}
          hint={mode === 'register' ? 'От 12 символов' : undefined}
        >
          <Input
            ref={passwordRef}
            name="password"
            type={visible ? 'text' : 'password'}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            {...(mode === 'register' ? SAFARI_PASSWORD_RULES : undefined)}
            leadingIcon="lock"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value)
              if (errors.password) setErrors((current) => ({ ...current, password: undefined }))
            }}
            trailing={
              <>
                {mode === 'register' && (
                  <IconButton
                    icon="key"
                    size="sm"
                    label="Сгенерировать надёжный пароль"
                    onClick={() => void generate()}
                  />
                )}
                <IconButton
                  icon={visible ? 'eye-off' : 'eye'}
                  size="sm"
                  label={visible ? 'Скрыть пароль' : 'Показать пароль'}
                  tooltip={false}
                  aria-pressed={visible}
                  onClick={() => setVisible((current) => !current)}
                />
              </>
            }
          />
        </Field>
      </div>
      <Button type="submit" variant="primary" size="lg" loading={submitting} className="w-full">
        {mode === 'login' ? 'Войти' : 'Создать аккаунт'}
      </Button>
    </form>
  )
}
