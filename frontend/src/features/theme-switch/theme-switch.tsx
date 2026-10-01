import { type ThemePreference, useTheme } from '@/shared/lib/theme'
import { SegmentedControl, type SegmentedOption } from '@/shared/ui'

const OPTIONS: SegmentedOption<ThemePreference>[] = [
  { value: 'light', label: 'Светлая', icon: 'sun' },
  { value: 'dark', label: 'Тёмная', icon: 'moon' },
  { value: 'system', label: 'Как в системе', icon: 'device-desktop' },
]

/** Выбор темы. Компактный вариант (только иконки) — для шапки, полный — для настроек. */
export function ThemeSwitch({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference } = useTheme()
  return (
    <SegmentedControl<ThemePreference>
      aria-label="Тема"
      size="sm"
      iconOnly={compact}
      value={preference}
      onValueChange={setPreference}
      options={OPTIONS}
    />
  )
}
