import { DEFAULT_PASSWORD_LENGTH, generatePassword, PASSWORD_CLASSES } from './password'

const RUNS = 10_000
const FORBIDDEN = /[lI1O0o]/
const ALLOWED = new RegExp(
  `^[${Object.values(PASSWORD_CLASSES)
    .join('')
    .replace(/[\]\\^-]/g, '\\$&')}]+$`,
)

describe('generatePassword', () => {
  it('по умолчанию даёт 20 символов, как требует сервер (12–128)', () => {
    expect(DEFAULT_PASSWORD_LENGTH).toBe(20)
    expect(generatePassword()).toHaveLength(20)
  })

  it(`на ${RUNS} прогонах: длина, алфавит, без похожих символов, все четыре класса`, () => {
    for (let i = 0; i < RUNS; i++) {
      const password = generatePassword()
      expect(password).toHaveLength(20)
      expect(password).toMatch(ALLOWED)
      expect(password).not.toMatch(FORBIDDEN)
      expect(password).toMatch(/[a-z]/)
      expect(password).toMatch(/[A-Z]/)
      expect(password).toMatch(/\d/)
      expect(password).toMatch(/[-_.!@#%+=]/)
    }
  })

  it('подряд даёт разные значения', () => {
    const seen = new Set(Array.from({ length: 1_000 }, () => generatePassword()))
    expect(seen.size).toBe(1_000)
  })

  it('учитывает длину и не даёт короче четырёх символов (по одному на класс)', () => {
    expect(generatePassword(4)).toHaveLength(4)
    expect(generatePassword(128)).toHaveLength(128)
    expect(() => generatePassword(3)).toThrow(RangeError)
    expect(() => generatePassword(12.5)).toThrow(RangeError)
  })

  it('каждый символ алфавита встречается: нет смещения по позициям и классам', () => {
    const counts = new Map<string, number>()
    for (let i = 0; i < 2_000; i++) {
      for (const char of generatePassword()) counts.set(char, (counts.get(char) ?? 0) + 1)
    }
    const alphabet = Object.values(PASSWORD_CLASSES).join('')
    for (const char of alphabet) expect(counts.get(char) ?? 0).toBeGreaterThan(0)
    // Первая позиция не закреплена за классом: тасование работает.
    const firsts = new Set(Array.from({ length: 400 }, () => generatePassword()[0]))
    const classesInFirst = Object.values(PASSWORD_CLASSES).filter((cls) =>
      [...firsts].some((char) => cls.includes(char as string)),
    )
    expect(classesInFirst).toHaveLength(4)
  })

  it('не использует Math.random', () => {
    const spy = vi.spyOn(Math, 'random')
    generatePassword()
    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })
})
