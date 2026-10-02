import { type DragEvent, type ReactNode, useId, useRef, useState } from 'react'
import { cn } from '@/shared/lib/cn'
import { Button } from '../button/button'
import { Icon, type IconName } from '../icon'

export interface FileDropProps {
  /** Расширения через запятую: ".txt,.md,.docx,.pdf". */
  accept: string
  onFiles: (files: File[]) => void
  multiple?: boolean
  disabled?: boolean
  /** Заголовок зоны: «Перетащите документ». */
  title: ReactNode
  /** Строка под заголовком: допустимые форматы и размер. */
  hint?: ReactNode
  icon?: IconName
  /** Подпись кнопки выбора. */
  buttonLabel?: string
  size?: 'sm' | 'md'
  className?: string
}

/** Есть ли в перетаскивании файлы (а не текст или ссылка). */
export function dragHasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

/**
 * Зона загрузки файлов: перетаскивание и кнопка выбора. Пунктир Иней в покое,
 * при наведении файла — рамка и подложка Тока. Скрытый input доступен с клавиатуры через кнопку.
 */
export function FileDrop({
  accept,
  onFiles,
  multiple = false,
  disabled = false,
  title,
  hint,
  icon = 'file-upload',
  buttonLabel = 'Выбрать файл',
  size = 'md',
  className,
}: FileDropProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)

  const take = (list: FileList | null) => {
    const files = Array.from(list ?? [])
    if (files.length) onFiles(multiple ? files : files.slice(0, 1))
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: зона только принимает перетаскивание; с клавиатуры — кнопка выбора внутри
    <div
      data-dragging={dragging || undefined}
      data-disabled={disabled || undefined}
      onDragEnter={(event) => {
        if (disabled || !dragHasFiles(event)) return
        event.preventDefault()
        depth.current += 1
        setDragging(true)
      }}
      onDragOver={(event) => {
        if (disabled || !dragHasFiles(event)) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      }}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1)
        if (depth.current === 0) setDragging(false)
      }}
      onDrop={(event) => {
        if (disabled) return
        event.preventDefault()
        depth.current = 0
        setDragging(false)
        take(event.dataTransfer.files)
      }}
      className={cn(
        'relative flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border-strong bg-bg-subtle text-center',
        'transition-[border-color,background-color,box-shadow] duration-base ease-soft',
        'data-[dragging]:border-accent data-[dragging]:bg-accent-subtle data-[dragging]:shadow-glow',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-60',
        size === 'md' ? 'px-6 py-8' : 'px-4 py-5',
        className,
      )}
    >
      <span
        className={cn(
          'grid place-items-center rounded-lg border border-border bg-surface text-fg-muted shadow-xs transition-colors duration-base',
          size === 'md' ? 'size-10' : 'size-8',
          dragging && 'border-accent/40 text-accent-fg',
        )}
      >
        <Icon name={icon} size={size === 'md' ? 20 : 16} />
      </span>
      <div className="flex flex-col gap-0.5">
        <span className="type-subheading text-fg">{title}</span>
        {hint && <span className="type-caption text-fg-subtle">{hint}</span>}
      </div>
      <Button
        size="sm"
        variant="secondary"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        aria-controls={inputId}
      >
        {buttonLabel}
      </Button>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        onChange={(event) => {
          take(event.target.files)
          event.target.value = ''
        }}
      />
    </div>
  )
}
