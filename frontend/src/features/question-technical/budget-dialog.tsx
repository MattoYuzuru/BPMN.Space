import { useState } from 'react'
import type { RunBudget } from '@/entities/run'
import { Button, Dialog, DialogContent, Field, Input } from '@/shared/ui'

const FORM_ID = 'raise-budget-form'

/** Поднять бюджет ждущего прогона (RFC-0006): новый лимит в долларах и/или токенах. */
export function RaiseBudgetDialog({
  open,
  onOpenChange,
  onSubmit,
  pending,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (budget: RunBudget) => void
  pending?: boolean
}) {
  const [cost, setCost] = useState('')
  const [tokens, setTokens] = useState('')
  const costValue = Number.parseFloat(cost.replace(',', '.'))
  const tokensValue = Number.parseInt(tokens, 10)
  const budget: RunBudget = {
    cost_usd: Number.isFinite(costValue) && costValue > 0 ? costValue : null,
    tokens: Number.isFinite(tokensValue) && tokensValue > 0 ? tokensValue : null,
  }
  const valid = budget.cost_usd !== null || budget.tokens !== null
  const close = () => {
    setCost('')
    setTokens('')
    onOpenChange(false)
  }
  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        size="sm"
        title="Поднять бюджет"
        description="Прогон продолжится с первого этапа. Уже потраченное входит в новый бюджет."
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
            if (valid) onSubmit(budget)
          }}
        >
          <Field label="В долларах" optional hint="Например, 15">
            <Input
              inputMode="decimal"
              value={cost}
              onChange={(event) => setCost(event.target.value)}
            />
          </Field>
          <Field label="В токенах" optional hint="Вход и ответ вместе">
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
