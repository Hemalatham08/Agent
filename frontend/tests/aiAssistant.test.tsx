import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGetAiModels, mockSwitchAiModel, mockChat } = vi.hoisted(() => ({
  mockGetAiModels: vi.fn(),
  mockSwitchAiModel: vi.fn(),
  mockChat: vi.fn(),
}))

vi.mock('../src/services/api', () => ({
  API_BASE_URL: 'http://127.0.0.1:8000',
  aiModelLabel: (info: { provider: string; model: string }) => {
    if (info.provider === 'ollama') {
      return 'Ollama — Llama 3.2'
    }
    if (info.provider === 'llamacpp') {
      return 'Qwen3 1.7B'
    }
    return `${info.model} (${info.provider})`
  },
  erpApi: {
    chat: mockChat,
    getAiModels: mockGetAiModels,
    getActiveAiModel: vi.fn(),
    switchAiModel: mockSwitchAiModel,
  },
}))

import AIAssistant from '../src/pages/AIAssistant'

interface ModelInfo {
  provider: string
  model: string
  base_url: string
  available: boolean
  active: boolean
  reason: string | null
}

const ollama: ModelInfo = {
  provider: 'ollama',
  model: 'llama3.2',
  base_url: 'http://127.0.0.1:11434',
  available: true,
  active: true,
  reason: null,
}

const llamacpp: ModelInfo = {
  provider: 'llamacpp',
  model: 'qwen3-1.7b',
  base_url: 'http://127.0.0.1:11435',
  available: true,
  active: false,
  reason: null,
}

function modelsResponse(activeProvider: 'ollama' | 'llamacpp') {
  const providers = [
    { ...ollama, active: activeProvider === 'ollama' },
    { ...llamacpp, active: activeProvider === 'llamacpp' },
  ]

  return {
    providers,
    active: activeProvider === 'ollama' ? providers[0] : providers[1],
  }
}

function openModelMenu() {
  fireEvent.click(screen.getByTestId('model-selector'))
  return screen.getByRole('dialog', { name: 'Select AI Model' })
}

describe('AIAssistant model switching', () => {
  let activeProvider: 'ollama' | 'llamacpp'

  beforeEach(() => {
    activeProvider = 'ollama'
    mockGetAiModels.mockReset()
    mockSwitchAiModel.mockReset()
    mockChat.mockReset()

    mockGetAiModels.mockImplementation(async () => modelsResponse(activeProvider))
    mockSwitchAiModel.mockImplementation(async (provider: string) => {
      const previousProvider = activeProvider
      activeProvider = provider === 'llamacpp' ? 'llamacpp' : 'ollama'
      return {
        ...(activeProvider === 'ollama' ? ollama : llamacpp),
        active: true,
        previous_provider: previousProvider,
      }
    })
  })

  async function renderAssistant() {
    render(<AIAssistant />)
    await waitFor(() => {
      expect(mockGetAiModels).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(screen.getByTestId('model-selector')).not.toBeDisabled()
    })
  }

  it('shows exactly the two required models with endpoints and active state', async () => {
    await renderAssistant()

    expect(screen.getByTestId('active-model')).toHaveTextContent(
      'Ollama — Llama 3.2',
    )
    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'ollama',
    )
    expect(screen.getByTestId('model-connection-status')).toHaveTextContent(
      'Connected',
    )
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByTestId('model-dropdown')).not.toBeInTheDocument()

    const dialog = openModelMenu()

    expect(within(dialog).getByText('Select AI Model')).toBeInTheDocument()
    expect(within(dialog).getByText('Model status')).toBeInTheDocument()

    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveAccessibleName(/Ollama — Llama 3\.2/)
    expect(options[1]).toHaveAccessibleName(/Qwen3 1\.7B/)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(options[1]).toHaveAttribute('aria-selected', 'false')

    expect(
      within(dialog).getByText(/ollama · http:\/\/127\.0\.0\.1:11434/),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(/llamacpp · http:\/\/127\.0\.0\.1:11435/),
    ).toBeInTheDocument()

    // Both health states come from the mocked backend response.
    expect(within(dialog).getByText('Active · Connected')).toBeInTheDocument()
    expect(within(dialog).getByText('Available')).toBeInTheDocument()
  })

  it('switches from Ollama to Qwen3 and shows the backend-active provider', async () => {
    await renderAssistant()

    openModelMenu()
    fireEvent.click(screen.getByRole('option', { name: /Qwen3 1\.7B/ }))

    await waitFor(() => {
      expect(mockSwitchAiModel).toHaveBeenCalledWith('llamacpp')
    })

    await waitFor(() => {
      expect(screen.getByTestId('active-model')).toHaveTextContent('Qwen3 1.7B')
    })

    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'llamacpp',
    )
    expect(mockGetAiModels).toHaveBeenCalledTimes(2)
    expect(screen.queryByTestId('model-dropdown')).not.toBeInTheDocument()
  })

  it('switches from Qwen3 back to Ollama and shows the backend-active provider', async () => {
    activeProvider = 'llamacpp'
    await renderAssistant()

    expect(screen.getByTestId('active-model')).toHaveTextContent('Qwen3 1.7B')
    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'llamacpp',
    )

    openModelMenu()
    fireEvent.click(
      screen.getByRole('option', { name: /Ollama — Llama 3\.2/ }),
    )

    await waitFor(() => {
      expect(mockSwitchAiModel).toHaveBeenCalledWith('ollama')
    })

    await waitFor(() => {
      expect(screen.getByTestId('active-model')).toHaveTextContent(
        'Ollama — Llama 3.2',
      )
    })

    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'ollama',
    )
    expect(mockGetAiModels).toHaveBeenCalledTimes(2)
  })

  it('removes any provider that is not one of the two supported models', async () => {
    mockGetAiModels.mockResolvedValueOnce({
      providers: [
        { ...ollama, active: true },
        { ...llamacpp, active: false },
        {
          provider: 'openai',
          model: 'gpt-4o',
          base_url: 'http://127.0.0.1:9999',
          available: true,
          active: false,
          reason: null,
        },
      ],
      active: { ...ollama, active: true },
    })

    await renderAssistant()
    openModelMenu()

    expect(screen.getAllByRole('option')).toHaveLength(2)
    expect(screen.queryByText(/9999/)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('option', { name: /openai|gpt-4o/i }),
    ).not.toBeInTheDocument()
  })

  it('shows an error and keeps the previous provider when switching fails', async () => {
    mockSwitchAiModel.mockRejectedValueOnce(
      new Error('Qwen3 1.7B is currently unavailable.'),
    )

    await renderAssistant()

    openModelMenu()
    fireEvent.click(screen.getByRole('option', { name: /Qwen3 1\.7B/ }))

    await waitFor(() => {
      expect(screen.getByTestId('model-error')).toHaveTextContent(
        'Qwen3 1.7B is currently unavailable.',
      )
    })

    expect(screen.getByTestId('active-model')).toHaveTextContent(
      'Ollama — Llama 3.2',
    )
    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'ollama',
    )
    expect(screen.getByTestId('model-connection-status')).toHaveTextContent(
      'Connected',
    )
  })

  it('disables the selector while a switch is in progress', async () => {
    let resolveSwitch: ((value: unknown) => void) | undefined
    mockSwitchAiModel.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSwitch = resolve
        }),
    )

    await renderAssistant()

    openModelMenu()
    fireEvent.click(screen.getByRole('option', { name: /Qwen3 1\.7B/ }))

    await waitFor(() => {
      expect(screen.getByTestId('model-selector')).toBeDisabled()
    })
    expect(screen.getByLabelText('Switching model')).toBeInTheDocument()
    expect(screen.getByTestId('model-connection-status')).toHaveTextContent(
      'Switching',
    )

    activeProvider = 'llamacpp'
    resolveSwitch?.({
      ...llamacpp,
      active: true,
      previous_provider: 'ollama',
    })

    await waitFor(() => {
      expect(screen.getByTestId('model-selector')).not.toBeDisabled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('active-model')).toHaveTextContent('Qwen3 1.7B')
    })
    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'llamacpp',
    )
  })

  it('does not call the switch API when selecting the active provider', async () => {
    await renderAssistant()

    openModelMenu()
    fireEvent.click(
      screen.getByRole('option', { name: /Ollama — Llama 3\.2/ }),
    )

    expect(mockSwitchAiModel).not.toHaveBeenCalled()
    expect(screen.queryByTestId('model-dropdown')).not.toBeInTheDocument()
  })

  it('closes the dropdown when clicking outside', async () => {
    await renderAssistant()

    openModelMenu()
    expect(screen.getByTestId('model-dropdown')).toBeInTheDocument()

    fireEvent.pointerDown(document.body)

    expect(screen.queryByTestId('model-dropdown')).not.toBeInTheDocument()
  })

  it('closes the dropdown with Escape and restores focus to the trigger', async () => {
    await renderAssistant()

    openModelMenu()
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByTestId('model-dropdown')).not.toBeInTheDocument()
    expect(screen.getByTestId('model-selector')).toHaveFocus()
  })

  it('supports arrow-key navigation between model options', async () => {
    await renderAssistant()

    const trigger = screen.getByTestId('model-selector')
    trigger.focus()
    fireEvent.keyDown(trigger, { key: 'ArrowDown' })

    const activeOption = screen.getByRole('option', {
      name: /Ollama — Llama 3\.2/,
    })
    await waitFor(() => {
      expect(activeOption).toHaveFocus()
    })

    fireEvent.keyDown(activeOption, { key: 'ArrowDown' })

    expect(
      screen.getByRole('option', { name: /Qwen3 1\.7B/ }),
    ).toHaveFocus()
  })

  it('renders live Qwen3 connectivity and Ollama unavailability', async () => {
    mockGetAiModels.mockResolvedValueOnce({
      providers: [
        {
          ...ollama,
          active: false,
          available: false,
          reason: 'Ollama is down.',
        },
        { ...llamacpp, active: true, available: true },
      ],
      active: { ...llamacpp, active: true, available: true },
    })

    await renderAssistant()
    const dialog = openModelMenu()

    expect(screen.getByTestId('active-model')).toHaveTextContent('Qwen3 1.7B')
    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'llamacpp',
    )
    expect(screen.getByTestId('model-connection-status')).toHaveTextContent(
      'Connected',
    )
    expect(within(dialog).getByText('Active · Connected')).toBeInTheDocument()
    expect(within(dialog).getByText('Unavailable')).toBeInTheDocument()
  })
})

describe('AIAssistant response timing', () => {
  let clock = 0

  beforeEach(() => {
    clock = 1_000
    // A controllable clock keeps request durations deterministic without depending
    // on real wall-clock time. The page measures with performance.now().
    vi.spyOn(performance, 'now').mockImplementation(() => clock)
    mockGetAiModels.mockReset()
    mockSwitchAiModel.mockReset()
    mockChat.mockReset()
    mockGetAiModels.mockImplementation(async () => modelsResponse('ollama'))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  async function renderAssistant() {
    render(<AIAssistant />)
    await waitFor(() => {
      expect(screen.getByTestId('model-selector')).not.toBeDisabled()
    })
  }

  function mockDurations(...durations: number[]) {
    let call = 0
    mockChat.mockImplementation(async () => {
      const duration = durations[Math.min(call, durations.length - 1)]
      call += 1
      clock += duration
      return { answer: `Answer ${call}`, model: 'llama3.2' }
    })
  }

  function ask(question: string) {
    const textarea = screen.getByPlaceholderText(
      'Ask about inventory, orders, invoices...',
    )
    fireEvent.change(textarea, { target: { value: question } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
  }

  function bubbleForAnswer(answer: string): HTMLElement {
    return screen.getByText(answer).closest(
      '[data-testid="assistant-bubble"]',
    ) as HTMLElement
  }

  function durationForAnswer(answer: string): HTMLElement {
    const bubble = bubbleForAnswer(answer)
    return within(bubble.parentElement as HTMLElement).getByTestId(
      'response-duration',
    )
  }

  it('shows a short response duration outside the assistant bubble', async () => {
    mockDurations(250)

    await renderAssistant()
    ask('How much free stock do we have for Hex Bolt M10?')

    const duration = await screen.findByTestId('response-duration')
    expect(duration).toHaveTextContent('Response generated in 0.25 seconds')
    expect(duration).toHaveTextContent('⏱️')

    const bubble = bubbleForAnswer('Answer 1')
    expect(bubble).toHaveTextContent('Answer 1')

    // Timing must be a sibling below the bubble, never inside its border.
    expect(bubble.contains(duration)).toBe(false)
    expect(bubble.parentElement).toBe(duration.parentElement)
    expect(duration.previousElementSibling).toBe(bubble)
    expect(duration.compareDocumentPosition(bubble)).toBe(
      Node.DOCUMENT_POSITION_PRECEDING,
    )

    // Shared column aligns the timing with the bubble's left edge.
    expect(bubble.parentElement?.className).toContain('items-start')

    // No horizontal divider remains on the timing element.
    expect(duration.className).not.toMatch(/(^|\s)border(-|\s|$)/)

    // The user message must not get a duration.
    expect(screen.getAllByTestId('response-duration')).toHaveLength(1)
  })

  it('shows a long response duration with two decimal places', async () => {
    mockDurations(9_876)

    await renderAssistant()
    ask('Show me every pending purchase order and its supplier.')

    const duration = await screen.findByTestId('response-duration')
    expect(duration).toHaveTextContent('9.88 seconds')
  })

  it('keeps a separate duration for each consecutive question', async () => {
    mockDurations(1_000, 2_500)

    await renderAssistant()

    ask('First question')
    await screen.findByText('Answer 1')
    await waitFor(() => {
      expect(screen.getAllByTestId('response-duration')).toHaveLength(1)
    })
    expect(durationForAnswer('Answer 1')).toHaveTextContent('1.00 seconds')

    ask('Second question')
    await screen.findByText('Answer 2')
    await waitFor(() => {
      expect(screen.getAllByTestId('response-duration')).toHaveLength(2)
    })
    expect(durationForAnswer('Answer 2')).toHaveTextContent('2.50 seconds')

    // Each timing sits directly below its own bubble.
    for (const answer of ['Answer 1', 'Answer 2']) {
      const bubble = bubbleForAnswer(answer)
      const duration = durationForAnswer(answer)
      expect(duration.previousElementSibling).toBe(bubble)
      expect(bubble.contains(duration)).toBe(false)
    }

    // Timing metadata must not leak into the API history payload.
    const secondPayload = mockChat.mock.calls[1][0] as {
      history: Array<Record<string, string>>
    }
    for (const entry of secondPayload.history) {
      expect(Object.keys(entry).sort()).toEqual(['content', 'role'])
    }
  })

  it('keeps the earlier duration when a later response fails', async () => {
    mockDurations(500)
    mockChat.mockImplementationOnce(async () => {
      clock += 500
      return { answer: 'Answer 1', model: 'llama3.2' }
    })
    mockChat.mockImplementationOnce(async () => {
      clock += 3_000
      throw new Error('Could not reach the AI service.')
    })

    await renderAssistant()

    ask('Working question')
    await screen.findByText('Answer 1')
    expect(screen.getByTestId('response-duration')).toHaveTextContent(
      '0.50 seconds',
    )

    ask('Failing question')
    await waitFor(() => {
      expect(screen.getByText('Could not get an answer')).toBeInTheDocument()
    })

    // The failure must not render a misleading successful duration.
    expect(screen.getAllByTestId('response-duration')).toHaveLength(1)
    expect(screen.queryByText('3.00 seconds')).not.toBeInTheDocument()
  })

  it('shows a loading indicator while the response is generating', async () => {
    let resolveChat: ((value: unknown) => void) | undefined
    mockChat.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveChat = resolve
        }),
    )

    await renderAssistant()
    ask('Slow question')

    expect(await screen.findByText('Querying ERP data...')).toBeInTheDocument()
    expect(screen.queryByTestId('response-duration')).not.toBeInTheDocument()

    clock += 4_820
    resolveChat?.({ answer: 'Answer after tool execution', model: 'llama3.2' })

    expect(await screen.findByTestId('response-duration')).toHaveTextContent(
      '4.82 seconds',
    )
    expect(screen.queryByText('Querying ERP data...')).not.toBeInTheDocument()
  })
})

describe('AIAssistant ERP tables', () => {
  const dispatchToolCall = {
    tool_name: 'erp.dispatches.list',
    status: 'succeeded',
    arguments: {},
    duration_ms: 18,
    error: null,
    output: {
      ok: true,
      data: {
        items: [
          {
            dispatch_id: 'DSP001',
            so_id: 'SO001',
            dispatch_date: '2026-02-10',
            status: 'Dispatched',
            carrier: 'BlueDart',
            tracking_number: 'BD123456',
          },
          {
            dispatch_id: 'DSP002',
            so_id: 'SO002',
            dispatch_date: null,
            status: 'Partially Dispatched',
            carrier: null,
            tracking_number: null,
          },
        ],
        row_count: 2,
        truncated: false,
      },
    },
  }

  beforeEach(() => {
    mockGetAiModels.mockReset()
    mockSwitchAiModel.mockReset()
    mockChat.mockReset()
    mockGetAiModels.mockImplementation(async () => modelsResponse('ollama'))
  })

  async function renderAssistant() {
    render(<AIAssistant />)
    await waitFor(() => {
      expect(screen.getByTestId('model-selector')).not.toBeDisabled()
    })
  }

  function ask(question: string) {
    const textarea = screen.getByPlaceholderText(
      'Ask about inventory, orders, invoices...',
    )
    fireEvent.change(textarea, { target: { value: question } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
  }

  it('renders real dispatch tool results as a table inside the bubble', async () => {
    mockChat.mockResolvedValueOnce({
      answer: 'Two dispatch records were found.',
      model: 'llama3.2',
      tool_calls: [dispatchToolCall],
    })

    await renderAssistant()
    ask('Which dispatches need attention?')

    const table = await screen.findByTestId('erp-data-table')
    expect(table).toHaveAttribute('data-table-id', 'dispatches')

    for (const header of [
      'Dispatch ID',
      'Sales Order ID',
      'Status',
      'Carrier',
      'Tracking Number',
      'Dispatch Date',
      'Notes / Issues',
    ]) {
      expect(within(table).getByText(header)).toBeInTheDocument()
    }

    expect(within(table).getByText('DSP001')).toBeInTheDocument()
    expect(within(table).getByText('BlueDart')).toBeInTheDocument()
    expect(within(table).getByText('Partially Dispatched')).toBeInTheDocument()
    expect(within(table).getByText(/Partial dispatch/)).toBeInTheDocument()
    expect(
      within(table).getByText(/Tracking number not recorded/),
    ).toBeInTheDocument()

    // Missing ERP values are shown as an em dash, never invented.
    expect(
      within(table).getAllByText('—').length,
    ).toBeGreaterThanOrEqual(3)

    // The summary answer is preserved above the table.
    expect(screen.getByTestId('assistant-bubble')).toHaveTextContent(
      'Two dispatch records were found.',
    )
    expect(
      screen.getByTestId('assistant-bubble').contains(table),
    ).toBe(true)

    // Timing still renders as its own sibling below the bubble.
    const duration = screen.getByTestId('response-duration')
    expect(duration.previousElementSibling).toBe(
      screen.getByTestId('assistant-bubble'),
    )
  })

  it('renders markdown tables produced in the answer', async () => {
    mockChat.mockResolvedValueOnce({
      answer: [
        'Two dispatch records were found.',
        '',
        '| Dispatch ID | Status | Carrier |',
        '| --- | --- | --- |',
        '| DSP001 | Dispatched | BlueDart |',
        '| DSP002 | Partially Dispatched | — |',
      ].join('\n'),
      model: 'llama3.2',
    })

    await renderAssistant()
    ask('Show dispatch records')

    const table = await screen.findByTestId('erp-data-table')
    expect(within(table).getByText('Dispatch ID')).toBeInTheDocument()
    expect(within(table).getByText('DSP002')).toBeInTheDocument()
    expect(screen.queryByText(/\| --- \|/)).not.toBeInTheDocument()
    expect(screen.getByTestId('assistant-bubble')).toHaveTextContent(
      'Two dispatch records were found.',
    )
    expect(screen.getAllByTestId('erp-data-table')).toHaveLength(1)
  })

  it('keeps a separate table for each consecutive assistant response', async () => {
    mockChat
      .mockResolvedValueOnce({
        answer: 'Dispatch records:',
        model: 'llama3.2',
        tool_calls: [dispatchToolCall],
      })
      .mockResolvedValueOnce({
        answer: 'Product records:',
        model: 'llama3.2',
        tool_calls: [
          {
            tool_name: 'erp.products.search',
            status: 'succeeded',
            output: {
              ok: true,
              data: {
                items: [
                  {
                    product_id: 'PRD001',
                    sku: 'HB-M10',
                    product_name: 'Hex Bolt M10',
                    category: 'Fastener',
                    material: 'Steel',
                    size: 'M10',
                    grade: '8.8',
                    unit: 'Nos',
                  },
                ],
                row_count: 1,
                truncated: false,
              },
            },
          },
        ],
      })

    await renderAssistant()

    ask('Show dispatches')
    await screen.findByText('Dispatch records:')

    ask('Show products')
    await screen.findByText('Product records:')

    await waitFor(() => {
      expect(screen.getAllByTestId('erp-data-table')).toHaveLength(2)
    })

    const tables = screen.getAllByTestId('erp-data-table')
    expect(tables[0]).toHaveAttribute('data-table-id', 'dispatches')
    expect(tables[1]).toHaveAttribute('data-table-id', 'products')

    // User messages never render tables.
    expect(screen.getAllByTestId('assistant-bubble')).toHaveLength(2)
  })
})
