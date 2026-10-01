import { screen } from '@testing-library/react'
import { renderUi } from '@/test/render'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './tabs'

describe('Tabs', () => {
  it('переключает панели стрелками и связывает вкладку с панелью', async () => {
    const { user } = renderUi(
      <Tabs defaultValue="sources">
        <TabsList aria-label="Разделы проекта">
          <TabsTrigger value="sources">Источники</TabsTrigger>
          <TabsTrigger value="questions" count={4}>
            Вопросы
          </TabsTrigger>
        </TabsList>
        <TabsContent value="sources">Список источников</TabsContent>
        <TabsContent value="questions">Список вопросов</TabsContent>
      </Tabs>,
    )
    const sources = screen.getByRole('tab', { name: 'Источники' })
    expect(sources).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Список источников')

    sources.focus()
    await user.keyboard('{ArrowRight}')
    const questions = screen.getByRole('tab', { name: /Вопросы/ })
    expect(questions).toHaveFocus()
    expect(questions).toHaveAttribute('aria-selected', 'true')
    expect(questions).toHaveTextContent('4')
    const panel = screen.getByRole('tabpanel')
    expect(panel).toHaveTextContent('Список вопросов')
    expect(panel).toHaveAttribute('aria-labelledby', questions.id)
  })
})
