import { render, screen } from '@testing-library/react'
import { CostMeter } from './cost-meter'

describe('CostMeter', () => {
  it('показывает диапазон оценки и долю бюджета', () => {
    render(<CostMeter label="Оценка прогона" estimate={{ min: 1.8, max: 3.2 }} budget={10} />)
    expect(screen.getByRole('group', { name: 'Оценка прогона' })).toBeInTheDocument()
    expect(screen.getByText(/≈ \$1,8–3,2/)).toBeInTheDocument()
    expect(screen.getByText(/из \$10/)).toBeInTheDocument()
    const bar = screen.getByTestId('cost-meter-bar')
    const band = bar.querySelector('[data-part="estimate"]') as HTMLElement
    expect(band.style.left).toBe('18%')
    expect(band.style.width).toBe('14%')
    expect(bar.querySelector('[data-part="spent"]')).toBeNull()
    expect(screen.queryByText('Выше бюджета')).toBeNull()
  })

  it('показывает потраченное и остаток бюджета', () => {
    render(<CostMeter label="Бюджет" spent={2.71} budget={10} />)
    expect(screen.getByText(/\$2,71/)).toBeInTheDocument()
    expect(screen.getByText(/из \$10/)).toBeInTheDocument()
    expect(screen.getByText(/Осталось \$7,29/)).toBeInTheDocument()
    const spent = screen
      .getByTestId('cost-meter-bar')
      .querySelector('[data-part="spent"]') as Element
    expect((spent as HTMLElement).style.width).toBe('27.1%')
  })

  it('превышение бюджета — тревожный тон', () => {
    render(<CostMeter spent={12} budget={10} />)
    const warning = screen.getByText('Выше бюджета')
    expect(warning).toHaveClass('text-danger-fg')
    const spent = screen.getByTestId('cost-meter-bar').querySelector('[data-part="spent"]')
    expect(spent).toHaveClass('bg-danger')
    expect(screen.queryByText(/Осталось/)).toBeNull()
  })

  it('неполная оценка помечена', () => {
    render(<CostMeter estimate={{ min: 1, max: 2 }} budget={10} incomplete />)
    expect(screen.getByText(/Неполная оценка/)).toBeInTheDocument()
  })

  it('оценка может превысить бюджет — предупреждение, но не «выше»', () => {
    render(<CostMeter label="Оценка" estimate={{ min: 8, max: 14 }} budget={10} />)
    expect(screen.getByText('Может превысить бюджет')).toHaveClass('text-amber-fg')
    expect(screen.queryByText('Выше бюджета')).toBeNull()
  })

  it('фактическое превышение и неполная оценка видны одновременно', () => {
    render(<CostMeter spent={12} budget={10} estimate={{ min: 8, max: 14 }} incomplete />)
    expect(screen.getByText('Выше бюджета')).toHaveClass('text-danger-fg')
    expect(screen.getByText('Может превысить бюджет')).toBeInTheDocument()
    expect(screen.getByText(/Неполная оценка/)).toBeInTheDocument()
  })

  it('нулевой или отрицательный бюджет — бюджета нет: ни полосы, ни деления', () => {
    const { rerender } = render(<CostMeter spent={2} budget={0} />)
    expect(screen.queryByTestId('cost-meter-bar')).toBeNull()
    expect(screen.getByText('$2')).toBeInTheDocument()
    rerender(<CostMeter spent={2} budget={-5} />)
    expect(screen.queryByTestId('cost-meter-bar')).toBeNull()
  })

  it('без бюджета — только сумма, без полосы', () => {
    render(<CostMeter label="Потрачено" spent={0.42} />)
    expect(screen.getByText(/\$0,42/)).toBeInTheDocument()
    expect(screen.queryByTestId('cost-meter-bar')).toBeNull()
  })

  it('без оценки и трат показывает только подпись, без полосы', () => {
    render(<CostMeter label="Стоимость" />)
    expect(screen.getByRole('group', { name: 'Стоимость' })).toBeInTheDocument()
    expect(screen.getByText('Стоимость')).toBeInTheDocument()
    expect(screen.queryByTestId('cost-meter-bar')).toBeNull()
  })
})
