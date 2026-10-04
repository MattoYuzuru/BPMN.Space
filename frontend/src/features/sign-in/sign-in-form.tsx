import { useRouter } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import {
  type AuthFormError,
  type AuthMode,
  authFormError,
  useLogin,
  useRegister,
  validateAuthForm,
} from '@/entities/session'
import { Button, Field, IconButton, Input, SegmentedControl, toast } from '@/shared/ui'

const MODES = [
  { value: 'login' as const, label: 'Вход' },
  { value: 'register' as const, label: 'Регистрация' },
]

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
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({})

  const fail = (error: unknown) => {
    const result: AuthFormError = authFormError(error, mode)
    if (result.field === 'form') toast.error(result.message)
    else setErrors({ [result.field]: result.message })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
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
          onModeChange(next)
        }}
        options={MODES}
        className="self-center"
      />
      <div className="flex flex-col gap-4">
        <Field label="Почта" error={errors.email}>
          <Input
            autoFocus
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
          label="Пароль"
          error={errors.password}
          hint={mode === 'register' ? 'От 12 символов' : undefined}
        >
          <Input
            type={visible ? 'text' : 'password'}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            leadingIcon="lock"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value)
              if (errors.password) setErrors((current) => ({ ...current, password: undefined }))
            }}
            trailing={
              <IconButton
                icon={visible ? 'eye-off' : 'eye'}
                size="sm"
                label={visible ? 'Скрыть пароль' : 'Показать пароль'}
                tooltip={false}
                aria-pressed={visible}
                onClick={() => setVisible((current) => !current)}
              />
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
