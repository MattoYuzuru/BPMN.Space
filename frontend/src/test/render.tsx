import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { TooltipProvider } from '@/shared/ui'

/** Рендер с глобальными провайдерами дизайн-системы и готовым userEvent. */
export function renderUi(ui: ReactElement) {
  const user = userEvent.setup()
  return { user, ...render(<TooltipProvider>{ui}</TooltipProvider>) }
}
