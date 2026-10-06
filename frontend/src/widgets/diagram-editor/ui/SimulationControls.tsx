import { Button, IconButton } from '@/shared/ui'
import type { DiagramEditorHandle, DiagramSimulation } from '../types'

const STATUS = {
  ready: 'Выберите начало процесса',
  playing: 'Процесс воспроизводится',
  paused: 'Пауза',
  waiting: 'Ожидание события',
  completed: 'Процесс завершён',
}

/** Управление воспроизведением доступно в readOnly: оно не меняет модель BPMN. */
export function SimulationControls({
  state,
  handle,
}: {
  state: DiagramSimulation
  handle: DiagramEditorHandle
}) {
  if (!state.active) return null
  const choose = state.choices.length > 0
  return (
    <fieldset
      className="de-playback-panel absolute top-3 left-3 z-20 flex max-w-[min(360px,calc(100%-24px))] flex-col gap-2 rounded-md border border-border bg-surface-raised p-2 shadow-md"
      aria-label="Воспроизведение процесса"
    >
      <div className="flex items-center gap-2">
        <span role="status" className="min-w-0 flex-1 type-ui text-fg-muted">
          {choose ? 'Выберите ветвь' : STATUS[state.status]}
        </span>
        {state.status !== 'ready' && state.status !== 'completed' && !choose ? (
          <IconButton
            icon={state.paused ? 'player-play' : 'player-pause'}
            label={state.paused ? 'Продолжить' : 'Пауза'}
            size="sm"
            onClick={() => (state.paused ? handle.startSimulation() : handle.pauseSimulation())}
          />
        ) : state.status === 'completed' ? (
          <IconButton
            icon="player-play"
            label="Повторить"
            size="sm"
            onClick={() => {
              handle.resetSimulation()
              handle.startSimulation()
            }}
          />
        ) : null}
        <IconButton
          icon="refresh"
          label="Сбросить воспроизведение"
          size="sm"
          onClick={() => handle.resetSimulation()}
        />
      </div>
      {state.message && <p className="type-ui text-amber-fg">{state.message}</p>}
      {state.status === 'ready' &&
        state.starts.map((start) => (
          <Button
            key={start.id}
            size="sm"
            className="justify-start overflow-hidden"
            onClick={() => handle.startSimulation(start.id)}
          >
            <span className="truncate">{start.label}</span>
          </Button>
        ))}
      {choose && <p className="type-caption text-fg-subtle">{state.choiceLabel}</p>}
      {state.choices.map((flow) => (
        <Button
          key={flow.id}
          size="sm"
          className="justify-start"
          onClick={() => handle.chooseSimulationFlow(flow.id)}
        >
          {flow.label}
        </Button>
      ))}
      {!choose &&
        state.waiting.map((event) => (
          <Button
            key={event.id}
            size="sm"
            className="justify-start overflow-hidden"
            onClick={() => handle.triggerSimulationEvent(event.id)}
          >
            <span className="truncate">Продолжить: {event.label}</span>
          </Button>
        ))}
    </fieldset>
  )
}
