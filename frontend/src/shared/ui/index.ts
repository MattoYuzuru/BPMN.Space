/**
 * Публичный API дизайн-системы. Экраны импортируют только отсюда: `import { Button } from '@/shared/ui'`.
 * Каталог, варианты и правила — docs/frontend/styleguide.md и живой стайлгайд /styleguide.
 * Spinner не экспортируется намеренно: загрузку областей показываем Skeleton, кнопок — Button loading.
 */

export { AssumptionFrame, type AssumptionFrameProps } from './assumption-frame/assumption-frame'
export { AudioLevel, type AudioLevelProps } from './audio-level/audio-level'
export { Avatar, type AvatarProps, initials } from './avatar/avatar'
export { Badge, type BadgeProps, type BadgeTone } from './badge/badge'
export { Beacon, type BeaconProps } from './beacon/beacon'
export { BrandMark, type BrandMarkProps } from './brand-mark/brand-mark'
export {
  Button,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
  buttonVariants,
} from './button/button'
export { Card, CardHeader, type CardHeaderProps, type CardProps } from './card/card'
export { Checkbox, type CheckboxProps } from './checkbox/checkbox'
export {
  type CoachAction,
  CoachCard,
  type CoachCardProps,
} from './coach-card/coach-card'
export { CommandPalette, preloadCommandPalette } from './command-palette/command-palette'
export type { CommandGroup, CommandItem, CommandPaletteProps } from './command-palette/types'
export { ConfirmDialog, type ConfirmDialogProps } from './dialog/confirm-dialog'
export {
  Dialog,
  DialogClose,
  DialogContent,
  type DialogContentProps,
  DialogTrigger,
} from './dialog/dialog'
export { Divider, type DividerProps } from './divider/divider'
export { DoneMark, type DoneMarkProps } from './done-mark/done-mark'
export {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from './dropdown-menu/dropdown-menu'
export { EmptyState, type EmptyStateProps } from './empty-state/empty-state'
export { Field, type FieldProps, useFieldControl } from './field/field'
export { dragHasFiles, FileDrop, type FileDropProps } from './file-drop/file-drop'
export { FlowLine, type FlowLineProps, type FlowLineState } from './flow-line/flow-line'
export { EntryScene } from './grid-backdrop/entry-scene'
export { GridBackdrop, type GridBackdropProps } from './grid-backdrop/grid-backdrop'
export { Icon, type IconName, type IconProps, type IconSize, iconNames } from './icon'
export { IconButton, type IconButtonProps } from './icon-button/icon-button'
export { Input, type InputProps } from './input/input'
export { Kbd, type KbdProps, type KeyName, keyLabel } from './kbd/kbd'
export {
  Popover,
  PopoverAnchor,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from './popover/popover'
export { Progress, type ProgressProps } from './progress/progress'
export { ProgressRing, type ProgressRingProps } from './progress-ring/progress-ring'
export {
  RadioGroup,
  RadioGroupItem,
  type RadioGroupItemProps,
  type RadioGroupProps,
} from './radio-group/radio-group'
export {
  type PanelImperativeHandle,
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
  useDefaultLayout,
  usePanelRef,
} from './resizable/resizable'
export { ScrollArea, type ScrollAreaProps } from './scroll-area/scroll-area'
export {
  SegmentedControl,
  type SegmentedControlProps,
  type SegmentedOption,
} from './segmented-control/segmented-control'
export { Select, type SelectOption, type SelectProps } from './select/select'
export {
  Sheet,
  SheetClose,
  SheetContent,
  type SheetContentProps,
  SheetTrigger,
} from './sheet/sheet'
export { Skeleton, SkeletonText } from './skeleton/skeleton'
export { type Rect, Spotlight, type SpotlightProps } from './spotlight/spotlight'
export { type StepItem, Stepper, type StepperProps, type StepStatus } from './stepper/stepper'
export {
  SUGGESTION_PREVIEW_CHARS,
  SuggestedTextarea,
  type SuggestedTextareaProps,
  suggestionPreview,
} from './suggested-textarea/suggested-textarea'
export { Switch, type SwitchProps } from './switch/switch'
export { Tabs, TabsContent, TabsList, TabsTrigger, type TabsTriggerProps } from './tabs/tabs'
export { Tag, type TagProps } from './tag/tag'
export { Textarea, type TextareaProps } from './textarea/textarea'
export { Toaster, type ToastOptions, toast } from './toast/toast'
export { Tooltip, type TooltipProps, TooltipProvider } from './tooltip/tooltip'
export { Typewriter, type TypewriterProps } from './typewriter/typewriter'
export { VoiceInput, type VoiceInputProps } from './voice-input/voice-input'
