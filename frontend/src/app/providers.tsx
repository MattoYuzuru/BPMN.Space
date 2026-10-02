import { QueryClientProvider } from '@tanstack/react-query'
import { LazyMotion, MotionConfig } from 'motion/react'
import type { ReactNode } from 'react'
import { queryClient } from '@/app/query-client'
import { ThemeProvider } from '@/shared/lib/theme'
import { Toaster, TooltipProvider } from '@/shared/ui'

/** Возможности motion подгружаются отдельным чанком: в стартовом бандле только лёгкие `m.*`. */
const loadMotionFeatures = () => import('./motion-features').then((module) => module.default)

/** Все глобальные провайдеры: данные, тема, движение, подсказки, уведомления. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <LazyMotion features={loadMotionFeatures} strict>
          <MotionConfig reducedMotion="user">
            <TooltipProvider>
              {children}
              <Toaster />
            </TooltipProvider>
          </MotionConfig>
        </LazyMotion>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
