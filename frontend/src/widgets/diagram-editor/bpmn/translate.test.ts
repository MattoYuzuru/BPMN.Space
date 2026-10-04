import { localizeDom } from './simulation-localization'
import { translate, translateSimulationMessage, translateUiText } from './translate'

describe('translate (сервис bpmn-js)', () => {
  it('переводит строки палитры, меню и панели свойств', () => {
    expect(translate('Create task')).toBe('Задача')
    expect(translate('Change element')).toBe('Изменить тип')
    expect(translate('User task')).toBe('Пользовательская задача')
    expect(translate('General')).toBe('Основное')
  })

  it('подставляет значения в шаблоны', () => {
    expect(translate('Open {element}', { element: 'Подпроцесс' })).toBe('Открыть «Подпроцесс»')
    expect(translate('List contains {numOfItems} items', { numOfItems: 3 })).toBe(
      'Элементов в списке: 3',
    )
    expect(translate('Unknown {x}')).toBe('Unknown {x}')
  })

  it('собирает составные подписи событий из заголовка панели свойств', () => {
    expect(translate('Timer Boundary Event (Non Interrupting)')).toBe(
      'Граничное событие: таймер (без прерывания)',
    )
    expect(translate('Message Start Event')).toBe('Начальное событие: сообщение')
    expect(translate('End Event')).toBe('Конечное событие')
  })

  it('неизвестную строку оставляет как есть', () => {
    expect(translate('Some new label')).toBe('Some new label')
  })
})

describe('симуляция токена', () => {
  it('переводит сообщения журнала и уведомлений, включая шаблоны', () => {
    expect(translateSimulationMessage('Process started')).toBe('Процесс запущен')
    expect(translateSimulationMessage('Reset Simulation')).toBe('Таймлайн сброшен')
    expect(translateSimulationMessage('Оплата started')).toBe('Оплата: запуск')
    expect(translateSimulationMessage('Подать заявку')).toBe('Подать заявку')
  })

  it('подсказки кнопок переводятся отдельно от сообщений', () => {
    expect(translateUiText('Reset Simulation')).toBe('Сбросить таймлайн')
    expect(translateUiText('Focus process instance 2')).toBe('Показать экземпляр 2')
    expect(translateUiText('3 results found')).toBe('Найдено: 3')
    expect(translateUiText('Задача')).toBeUndefined()
  })

  it('localizeDom переводит подсказки и служебные подписи, но не текст схемы', async () => {
    const root = document.createElement('div')
    root.innerHTML = `
      <div class="bts-palette"><button class="bts-entry" title="Reset Simulation"></button></div>
      <div class="bts-log"><div class="bts-header">Simulation Log</div></div>
      <svg><text>Close</text></svg>`
    const observer = localizeDom(root)
    expect(root.querySelector('.bts-entry')?.getAttribute('title')).toBe('Сбросить таймлайн')
    expect(root.querySelector('.bts-header')?.textContent).toBe('Журнал таймлайна')
    expect(root.querySelector('text')?.textContent).toBe('Close')

    const pad = document.createElement('button')
    pad.className = 'bts-context-pad'
    pad.title = 'Trigger Event'
    root.appendChild(pad)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(pad.title).toBe('Запустить событие')
    observer.disconnect()
  })
})
