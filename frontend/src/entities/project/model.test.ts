import { describe, expect, it } from 'vitest'
import {
  isReadOnly,
  PROJECT_SCOPES,
  projectCapabilities,
  scopeFromSearch,
  scopeToSearch,
} from './model'

describe('projectCapabilities', () => {
  it('владелец может всё', () => {
    expect(projectCapabilities('owner', true)).toEqual({
      canEdit: true,
      canManage: true,
      canShare: true,
    })
  })

  it('редактор правит, но не удаляет проект и не управляет доступом', () => {
    expect(projectCapabilities('editor', true)).toEqual({
      canEdit: true,
      canManage: false,
      canShare: false,
    })
  })

  it('зритель только читает', () => {
    expect(projectCapabilities('viewer', true)).toEqual({
      canEdit: false,
      canManage: false,
      canShare: false,
    })
    expect(isReadOnly('viewer')).toBe(true)
    expect(isReadOnly('editor')).toBe(false)
  })
})

describe('область списка проектов', () => {
  it('из адреса берётся известная область, остальное — «все»', () => {
    expect(scopeFromSearch('shared')).toBe('shared')
    expect(scopeFromSearch('own')).toBe('own')
    expect(scopeFromSearch('examples')).toBe('examples')
    expect(scopeFromSearch('all')).toBe('all')
    expect(scopeFromSearch('everything')).toBe('all')
    expect(scopeFromSearch(undefined)).toBe('all')
    expect(scopeFromSearch(['own'])).toBe('all')
  })

  it('«все» в адрес не пишется, остальные — как есть', () => {
    expect(scopeToSearch('all')).toBeUndefined()
    expect(scopeToSearch('shared')).toBe('shared')
  })

  it('переключатель показывает четыре области в порядке «Все, Мои, Общие, Примеры»', () => {
    expect(PROJECT_SCOPES.map((scope) => scope.label)).toEqual(['Все', 'Мои', 'Общие', 'Примеры'])
  })
})
