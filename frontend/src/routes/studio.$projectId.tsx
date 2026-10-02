import { createFileRoute, redirect } from '@tanstack/react-router'

/** Совместимость со старыми ссылками: у каждого серверного проекта одно рабочее место. */
export const Route = createFileRoute('/studio/$projectId')({
  beforeLoad: ({ params }) => {
    throw redirect({ to: '/projects/$projectId', params })
  },
})
