import type { ReactNode } from 'react'
import { GridBackdrop } from './grid-backdrop'

/** Общая сцена входа и приглашения: живая сетка и содержимое поверх неё. */
export function EntryScene({ header, children }: { header: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex h-14 shrink-0 items-center justify-end gap-2 px-4 wide:px-5">
        {header}
      </header>
      <main className="relative isolate grid flex-1 place-items-center px-6 pb-16">
        <GridBackdrop pattern="grid" glow interactive />
        {children}
      </main>
    </div>
  )
}
