import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AssistantResponse } from '../src/components/ai/AssistantResponse'
import { ErpChart } from '../src/components/ai/ErpChart'
import type { ChartSpec } from '../src/services/api'

// Recharts only draws its <svg> when the chart receives positive pixel
// dimensions. jsdom has no layout engine, so ResizeObserver is stubbed to
// report the size a real browser would measure for the container.
const MEASURED_WIDTH = 640
const MEASURED_HEIGHT = 220

class MockResizeObserver implements ResizeObserver {
  private readonly callback: ResizeObserverCallback

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }

  observe(): void {
    this.callback(
      [
        {
          contentRect: {
            width: MEASURED_WIDTH,
            height: MEASURED_HEIGHT,
          },
        } as ResizeObserverEntry,
      ],
      this,
    )
  }

  unobserve(): void {}

  disconnect(): void {}
}

const salesChart: ChartSpec = {
  chart_type: 'bar',
  title: 'Sales revenue by product (booked)',
  data: [
    { x: 'PRD005', revenue: 2860 },
    { x: 'PRD001', revenue: 2400 },
    { x: 'PRD002', revenue: 1800 },
  ],
  x_field: 'key',
  y_fields: ['revenue'],
  x_label: 'product',
  y_label: 'Revenue',
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', MockResizeObserver)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ErpChart', () => {
  it('renders a positive-size Recharts surface for a product revenue spec', () => {
    const { container } = render(<ErpChart spec={salesChart} />)

    const surface = container.querySelector(
      'svg.recharts-surface[role="application"]',
    )
    expect(surface).not.toBeNull()
    expect(Number(surface?.getAttribute('width'))).toBe(MEASURED_WIDTH)
    expect(Number(surface?.getAttribute('height'))).toBe(MEASURED_HEIGHT)

    // The verified series must actually reach the chart, not just the shell.
    expect(container.querySelectorAll('.recharts-bar-rectangle').length).toBe(
      salesChart.data.length,
    )
  })

  it('renders nothing when the chart has no data points', () => {
    const { container } = render(
      <ErpChart spec={{ ...salesChart, data: [] }} />,
    )

    expect(container.querySelector('svg.recharts-surface')).toBeNull()
  })
})

describe('AssistantResponse charts', () => {
  it('renders one chart per backend chart spec alongside the answer text', () => {
    render(
      <AssistantResponse
        content="Revenue by product is summarised below."
        charts={[salesChart]}
      />,
    )

    expect(
      screen.getByText('Revenue by product is summarised below.'),
    ).toBeInTheDocument()
    expect(screen.getAllByTestId('erp-chart')).toHaveLength(1)
    expect(
      document.querySelectorAll('svg.recharts-surface[role="application"]'),
    ).toHaveLength(1)
    expect(
      document.querySelectorAll('.recharts-bar-rectangle').length,
    ).toBe(salesChart.data.length)
  })
})
