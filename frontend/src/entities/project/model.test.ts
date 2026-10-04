import { describe, expect, it } from 'vitest'
import { isReadOnly, projectCapabilities } from './model'

describe('projectCapabilities', () => {
  it('владелец может всё', () => {
    expect(projectCapabilities('owner')).toEqual({ canEdit: true, canManage: true })
  })

  it('редактор правит, но не удаляет проект и не управляет доступом', () => {
    expect(projectCapabilities('editor')).toEqual({ canEdit: true, canManage: false })
  })

  it('зритель только читает', () => {
    expect(projectCapabilities('viewer')).toEqual({ canEdit: false, canManage: false })
    expect(isReadOnly('viewer')).toBe(true)
    expect(isReadOnly('editor')).toBe(false)
  })
})
