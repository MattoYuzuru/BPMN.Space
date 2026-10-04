import { useState } from 'react'
import { IconButton, Popover, PopoverContent, PopoverTrigger, Tooltip } from '@/shared/ui'
import { VoiceCapture } from './voice-capture'

export interface VoiceDictationProps {
  /** Получает проверенный текст расшифровки. */
  onText: (text: string) => void
  /** Подпись кнопки завершения: «Отправить ответ», «Добавить в описание». */
  submitLabel: string
  submitIcon?: 'plus' | 'send'
  label?: string
  side?: 'left' | 'bottom'
  className?: string
}

/**
 * Надиктовать в поле: микрофон над полем открывает компактную запись, после распознавания
 * текст можно поправить и передать дальше. Один приём для ответа на вопрос и описания процесса.
 */
export function VoiceDictation({
  onText,
  submitLabel,
  submitIcon = 'plus',
  label = 'Надиктовать',
  side = 'left',
  className,
}: VoiceDictationProps) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip content={label}>
        <PopoverTrigger asChild>
          <IconButton
            icon="microphone"
            label={label}
            size="sm"
            tooltip={false}
            className={className}
          />
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent side={side} align={side === 'bottom' ? 'end' : 'start'} className="w-96">
        {open && (
          <VoiceCapture
            autoStart
            compact
            submitLabel={submitLabel}
            submitIcon={submitIcon}
            onSubmit={({ text }) => {
              setOpen(false)
              onText(text)
            }}
          />
        )}
      </PopoverContent>
    </Popover>
  )
}
