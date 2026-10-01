import type { ComponentProps } from 'react'
import { cn } from '@/shared/lib/cn'

/** Системный выбор файла для кнопок с отдельным видимым действием загрузки. */
export function FileInput({ className, tabIndex = -1, ...props }: ComponentProps<'input'>) {
  return <input {...props} type="file" tabIndex={tabIndex} className={cn('sr-only', className)} />
}
