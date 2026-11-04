import { screen } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { AgentModeHint } from './agent-mode-hint'

beforeEach(() => window.localStorage.clear())

it('показывает подсказку про агентный режим и запоминает закрытие', async () => {
  const { user } = renderUi(<AgentModeHint enabled />)
  expect(screen.getByText(/модель сама читает источники инструментами/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Понятно' }))
  expect(screen.queryByTestId('agent-mode-hint')).toBeNull()
  expect(window.localStorage.getItem('arkhitektor:agent-mode-hint-dismissed')).toBe('1')
})

it('не показывается, когда режим недоступен, и после закрытия', () => {
  window.localStorage.setItem('arkhitektor:agent-mode-hint-dismissed', '1')
  const { unmount } = renderUi(<AgentModeHint enabled />)
  expect(screen.queryByTestId('agent-mode-hint')).toBeNull()
  unmount()
  window.localStorage.clear()
  renderUi(<AgentModeHint enabled={false} />)
  expect(screen.queryByTestId('agent-mode-hint')).toBeNull()
})
