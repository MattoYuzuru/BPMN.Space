import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { queryClient } from '@/app/query-client'
import { ThemeProvider } from '@/shared/lib/theme'
import { Toaster, TooltipProvider } from '@/shared/ui'

/** Все глобальные провайдеры: данные, тема, подсказки, уведомления. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          {children}
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
