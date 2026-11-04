import { useEffect, useState } from 'react'
import type { RunBudget } from '@/entities/run'
import { formatMoney, formatTokens } from '@/shared/lib/format'
import { parseMoneyInput, parseTokensInput } from '@/shared/lib/number-input'
import { Button, Dialog, DialogContent, Field, Input } from '@/shared/ui'

const FORM_ID = 'raise-budget-form'

/**
 * Поднять бюджет ждущего прогона (RFC-0006). Показывает текущий лимит и заполняет поля из него:
 * оба ограничения передаются вместе, снять токеновый лимит пустым полем нельзя.
 */
export function RaiseBudgetDialog({
  open,
  onOpenChange,
  onSubmit,
  current,
  pending,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (budget: RunBudget) => void
  /** Текущий бюджет прогона из RunView; null — лимита не было. */
  current?: RunBudget | null
  pending?: boolean
}) {
  const [cost, setCost] = useState('')
  const [tokens, setTokens] = useState('')

  // Новый диалог начинается с текущих лимитов: их можно поднять, но не потерять.
  useEffect(() => {
    if (!open) return
    setCost(current?.cost_usd != null ? String(current.cost_usd) : '')
    setTokens(current?.tokens != null ? String(current.tokens) : '')
  }, [open, current])

  const costParsed = parseMoneyInput(cost)
  const tokensParsed = parseTokensInput(tokens)
  const currentCost = current?.cost_usd ?? null
  const currentTokens = current?.tokens ?? null
  // Пустое поле сохраняет текущий лимит; введённое — новое значение.
  const nextCost = cost.trim() ? costParsed.value : currentCost
  const nextTokens = tokens.trim() ? tokensParsed.value : currentTokens
  const costError =
    costParsed.error ??
    (nextCost !== null && currentCost !== null && nextCost < currentCost
      ? `Не меньше текущего: ${formatMoney(currentCost, 'USD')}`
      : null)
  const tokensError =
    tokensParsed.error ??
    (nextTokens !== null && currentTokens !== null && nextTokens < currentTokens
      ? `Не меньше текущего: ${formatTokens(currentTokens)}`
      : null)
  const increased =
    (nextCost !== null && (currentCost === null || nextCost > currentCost)) ||
    (nextTokens !== null && (currentTokens === null || nextTokens > currentTokens))
  const valid = !costError && !tokensError && increased

  const close = () => {
    setCost('')
    setTokens('')
    onOpenChange(false)
  }

  const hint =
    currentCost !== null || currentTokens !== null
      ? `Сейчас: ${[
          currentCost !== null ? formatMoney(currentCost, 'USD') : null,
          currentTokens !== null ? `${formatTokens(currentTokens)} токенов` : null,
        ]
          .filter(Boolean)
          .join(' и ')}. Уже потраченное входит в новый бюджет.`
      : 'Прогон продолжится с первого этапа. Уже потраченное входит в новый бюджет.'

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        size="sm"
        title="Поднять бюджет"
        description={hint}
        footer={
          <>
            <Button variant="ghost" onClick={close}>
              Отмена
            </Button>
            <Button
              variant="primary"
              type="submit"
              form={FORM_ID}
              loading={pending}
              disabled={!valid}
            >
              Поднять бюджет
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
            if (!valid) return
            onSubmit({
              cost_usd: nextCost,
              tokens: nextTokens,
            })
          }}
        >
          <Field label="В долларах" optional hint="Например, 15" error={costError ?? undefined}>
            <Input
              inputMode="decimal"
              value={cost}
              onChange={(event) => setCost(event.target.value)}
            />
          </Field>
          <Field
            label="В токенах"
            optional
            hint="Вход и ответ вместе"
            error={tokensError ?? undefined}
          >
            <Input
              inputMode="numeric"
              value={tokens}
              onChange={(event) => setTokens(event.target.value)}
            />
          </Field>
          <p className="type-caption text-fg-muted">
            Новый бюджет должен быть больше текущего — сервер не даст уменьшить лимит.
          </p>
        </form>
      </DialogContent>
    </Dialog>
  )
}
