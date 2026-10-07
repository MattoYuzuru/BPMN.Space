import { expect, test } from '@playwright/test'
import { createExampleProject, runViaApi } from './support'

test('цитата ведёт к фрагменту, фрагмент — к вопросу, а вопрос — обратно к источнику', async ({
  page,
  request,
}) => {
  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'build')
  const project = await (await request.get(`/api/v1/projects/${projectId}`)).json()
  const question = project.questions.find(
    (item: { about?: { source_id: string; quote: string } }) => item.about,
  )
  expect(question).toBeTruthy()
  const source = project.sources.find(
    (item: { id: string }) => item.id === question.about.source_id,
  )
  await page.goto(
    `/projects/${projectId}?source=${source.id}&mark=${encodeURIComponent(question.about.quote)}`,
  )
  let sourceDialog = page.getByRole('dialog', { name: source.title })
  await expect(sourceDialog).toBeVisible()
  await sourceDialog.locator('[data-testid="source-content"] [data-target="true"]').click()
  await page
    .getByRole('button', { name: `${question.code}: ${question.text}`, exact: true })
    .click()
  const questionDialog = page.getByRole('dialog').filter({ hasText: question.text })
  await expect(questionDialog).toBeVisible()
  await expect(sourceDialog).toBeHidden()
  await expect(page).toHaveURL(new RegExp(`question=${question.id}`))
  await questionDialog.getByRole('link').filter({ hasText: source.title }).first().click()
  sourceDialog = page.getByRole('dialog', { name: source.title })
  await expect(sourceDialog).toBeVisible()
  await expect(questionDialog).toBeHidden()
  await expect(sourceDialog.locator('[data-target="true"]')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(1)

  // Правка меняет текущий текст; прежняя ссылка честно объясняет отсутствие фрагмента.
  await sourceDialog.getByRole('button', { name: 'Править текст' }).click()
  await sourceDialog
    .getByRole('textbox', { name: 'Текст', exact: true })
    .fill('Аналитик согласует заявку. После согласования процесс завершается.')
  await sourceDialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(sourceDialog.getByRole('status')).toContainText('Цитата не найдена в текущем тексте')
  await expect(sourceDialog.getByRole('status')).toContainText(question.about.quote)
})
