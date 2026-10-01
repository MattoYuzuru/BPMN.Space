import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: () => (
    <main className="p-8">
      <h1>Архитектор BPMN</h1>
    </main>
  ),
})
