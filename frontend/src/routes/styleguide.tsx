import { createFileRoute } from '@tanstack/react-router'
import { StyleguidePage } from './-styleguide/styleguide-page'

/** Живой стайлгайд. Маршрут грузится отдельным чанком (autoCodeSplitting) — в стартовый бандл не входит. */
export const Route = createFileRoute('/styleguide')({
  component: StyleguidePage,
})
