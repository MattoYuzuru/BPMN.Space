import { describe, expect, it } from 'vitest'
import { parseIntegerInput, parseMoneyInput, parseTokensInput } from './number-input'

describe('разбор чисел в полях бюджета', () => {
  it('принимает пустое поле как «без ограничения»', () => {
    expect(parseMoneyInput('')).toEqual({ value: null, error: null })
    expect(parseMoneyInput('   ')).toEqual({ value: null, error: null })
    expect(parseTokensInput('')).toEqual({ value: null, error: null })
  })

  it('понимает разряды с пробелами и NBSP, точку и запятую', () => {
    expect(parseMoneyInput('100 000').value).toBe(100_000)
    expect(parseMoneyInput('100\u00A0000').value).toBe(100_000)
    expect(parseMoneyInput('1 000,50').value).toBe(1000.5)
    expect(parseMoneyInput('1000.5').value).toBe(1000.5)
    expect(parseMoneyInput('10').value).toBe(10)
    expect(parseTokensInput('100 000').value).toBe(100_000)
    expect(parseIntegerInput('100\u202F000').value).toBe(100_000)
  })

  it('не режет мусор до числа, а отдаёт ошибку', () => {
    expect(parseMoneyInput('10abc').value).toBeNull()
    expect(parseMoneyInput('10abc').error).toContain('сумму числом')
    expect(parseMoneyInput('abc').error).toBeTruthy()
    expect(parseMoneyInput('-5').error).toBeTruthy()
    expect(parseMoneyInput('1,2,3').error).toBeTruthy()
    expect(parseMoneyInput('1.234').error).toBeTruthy()
    expect(parseTokensInput('10,5').error).toContain('целое число токенов')
    expect(parseTokensInput('abc').error).toBeTruthy()
    expect(parseIntegerInput('-1').error).toBeTruthy()
  })
})
