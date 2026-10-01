import { useState } from 'react'
import { useHotkey } from '@/shared/hooks/use-hotkey'
import {
  Button,
  CommandPalette,
  ConfirmDialog,
  Dialog,
  DialogClose,
  DialogContent,
  DialogTrigger,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  Field,
  IconButton,
  Input,
  Kbd,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  Sheet,
  SheetContent,
  SheetTrigger,
  Switch,
  Textarea,
  Tooltip,
  toast,
} from '@/shared/ui'
import { Section, Specimen, SpecimenGrid } from './kit'

export function OverlaysSection() {
  const [showCitations, setShowCitations] = useState(true)
  const [paletteOpen, setPaletteOpen] = useState(false)
  useHotkey(['mod', 'k'], () => setPaletteOpen((open) => !open))

  return (
    <Section
      id="overlays"
      eyebrow="13 Компоненты"
      title="Меню, подсказки, окна"
      lead="Всплывающие слои выходят из своего элемента и уходят быстрее, чем пришли. Подсказка — название действия, а не инструкция. Подтверждение необратимого — ConfirmDialog, никогда window.confirm."
    >
      <SpecimenGrid>
        <Specimen title="DropdownMenu" note="иконки, клавиши, флажки, вложенное меню">
          <div className="flex items-center gap-3">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button trailingIcon="chevron-down">Скачать</Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem icon="file-code" shortcut={['mod', 's']}>
                  BPMN 2.0 (.bpmn)
                </DropdownMenuItem>
                <DropdownMenuItem icon="photo">Изображение SVG</DropdownMenuItem>
                <DropdownMenuItem icon="photo">Изображение PNG</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem icon="list-check">Отчёт проверки</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton icon="dots" label="Ещё" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Источник</DropdownMenuLabel>
                <DropdownMenuItem icon="pencil">Переименовать</DropdownMenuItem>
                <DropdownMenuItem icon="copy">Скопировать текст</DropdownMenuItem>
                <DropdownMenuCheckboxItem
                  checked={showCitations}
                  onCheckedChange={(value) => setShowCitations(value === true)}
                >
                  Цитаты на схеме
                </DropdownMenuCheckboxItem>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger icon="arrow-right">Переместить</DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuItem>Техприсоединение</DropdownMenuItem>
                    <DropdownMenuItem>Вывод в ремонт</DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem icon="trash" tone="danger">
                  Удалить
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </Specimen>

        <Specimen title="Tooltip и Popover" note="подсказка 450 мс, соседние сразу">
          <div className="flex flex-wrap items-center gap-3">
            <Tooltip content="Показать на схеме" shortcut={['mod', 'enter']}>
              <Button variant="ghost" leadingIcon="diagram">
                Наведите
              </Button>
            </Tooltip>
            <Tooltip content="Подсказка снизу" side="bottom">
              <Button variant="ghost">Снизу</Button>
            </Tooltip>
            <Popover>
              <PopoverTrigger asChild>
                <Button leadingIcon="adjustments">Параметры прогона</Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="flex flex-col gap-4">
                <div className="type-subheading text-fg">Параметры прогона</div>
                <Field label="Модель">
                  <Select
                    size="sm"
                    defaultValue="qwen"
                    options={[
                      { value: 'qwen', label: 'Qwen 3.6 35B' },
                      { value: 'alice', label: 'Alice AI LLM' },
                    ]}
                  />
                </Field>
                <Switch label="Строить сразу, без вопросов" />
              </PopoverContent>
            </Popover>
          </div>
        </Specimen>

        <Specimen title="Dialog и ConfirmDialog" note="фокус внутри, Esc закрывает">
          <div className="flex flex-wrap items-center gap-3">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="primary" leadingIcon="plus">
                  Новый проект
                </Button>
              </DialogTrigger>
              <DialogContent
                title="Новый проект"
                description="Проект — рабочее пространство одной схемы: источники, вопросы и версии."
                footer={
                  <>
                    <DialogClose asChild>
                      <Button variant="ghost">Отмена</Button>
                    </DialogClose>
                    <DialogClose asChild>
                      <Button variant="primary" onClick={() => toast.success('Проект создан')}>
                        Создать проект
                      </Button>
                    </DialogClose>
                  </>
                }
              >
                <div className="flex flex-col gap-4">
                  <Field label="Название">
                    <Input autoFocus placeholder="Например, Техприсоединение" />
                  </Field>
                  <Field label="Описание процесса" optional>
                    <Textarea minRows={3} placeholder="Можно добавить позже" />
                  </Field>
                </div>
              </DialogContent>
            </Dialog>
            <ConfirmDialog
              trigger={
                <Button tone="danger" leadingIcon="trash">
                  Удалить источник
                </Button>
              }
              title="Удалить источник?"
              description="Вопросы, закрытые по этому источнику, вернутся в открытые."
              confirmLabel="Удалить"
              tone="danger"
              onConfirm={() =>
                new Promise<void>((resolve) => window.setTimeout(resolve, 900)).then(() => {
                  toast('Источник удалён', {
                    action: {
                      label: 'Вернуть',
                      onClick: () => toast.success('Источник возвращён'),
                    },
                  })
                })
              }
            />
          </div>
        </Specimen>

        <Specimen title="Sheet и CommandPalette" note="панель справа, палитра по ⌘K">
          <div className="flex flex-wrap items-center gap-3">
            <Sheet>
              <SheetTrigger asChild>
                <Button leadingIcon="history">История версий</Button>
              </SheetTrigger>
              <SheetContent
                title="История версий"
                description="Схема сохраняется после каждого прогона и ручной правки."
                footer={<Button variant="primary">Восстановить версию</Button>}
              >
                <ol className="flex flex-col gap-3">
                  {['Версия 4, ручная правка', 'Версия 3, прогон', 'Версия 2, прогон'].map(
                    (title, index) => (
                      <li
                        key={title}
                        className="flex items-center justify-between rounded-md border border-border p-3"
                      >
                        <span className="type-ui text-fg">{title}</span>
                        <span className="type-caption text-fg-subtle" data-numeric>
                          {`1${index} октября`}
                        </span>
                      </li>
                    ),
                  )}
                </ol>
              </SheetContent>
            </Sheet>
            <Button leadingIcon="search" onClick={() => setPaletteOpen(true)}>
              Команды
              <Kbd keys={['mod', 'k']} className="ml-1" />
            </Button>
            <CommandPalette
              open={paletteOpen}
              onOpenChange={setPaletteOpen}
              groups={[
                {
                  heading: 'Проект',
                  items: [
                    {
                      id: 'source',
                      label: 'Добавить источник',
                      icon: 'file-upload',
                      shortcut: ['mod', 'u'],
                      onSelect: () => toast('Добавить источник'),
                    },
                    {
                      id: 'voice',
                      label: 'Записать голос',
                      icon: 'microphone',
                      onSelect: () => toast('Запись голоса'),
                    },
                    {
                      id: 'build',
                      label: 'Построить схему',
                      icon: 'diagram',
                      shortcut: ['mod', 'enter'],
                      onSelect: () => toast.success('Схема построена'),
                    },
                  ],
                },
                {
                  heading: 'Перейти',
                  items: [
                    {
                      id: 'questions',
                      label: 'Открытые вопросы',
                      icon: 'message-question',
                      onSelect: () => toast('Вопросы'),
                    },
                    {
                      id: 'history',
                      label: 'История версий',
                      icon: 'history',
                      keywords: ['версия', 'откат'],
                      onSelect: () => toast('История'),
                    },
                  ],
                },
              ]}
            />
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
