import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  SpeechRecognitionErrorEventLike,
  SpeechRecognitionEventLike,
  SpeechRecognitionLike,
  SpeechRecognitionResultListLike,
} from '../src/voice_module'

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

const modelsResponse = {
  providers: [
    {
      provider: 'ollama',
      model: 'llama3.2',
      base_url: 'http://127.0.0.1:11434',
      available: true,
      active: true,
      reason: null,
    },
  ],
  active: {
    provider: 'ollama',
    model: 'llama3.2',
    base_url: 'http://127.0.0.1:11434',
    available: true,
    active: true,
    reason: null,
  },
}

class FakeSpeechRecognition implements SpeechRecognitionLike {
  static instances: FakeSpeechRecognition[] = []

  continuous = false
  interimResults = false
  lang = ''
  maxAlternatives = 1
  onstart: (() => void) | null = null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null = null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null = null
  onend: (() => void) | null = null
  start = vi.fn(() => {
    this.onstart?.()
  })
  stop = vi.fn(() => {
    this.onend?.()
  })
  abort = vi.fn(() => {
    this.onend?.()
  })

  constructor() {
    FakeSpeechRecognition.instances.push(this)
  }

  emitResult(transcript: string, isFinal: boolean): void {
    const alternative = { transcript, confidence: 0.9 }
    const result = Object.assign([alternative], { isFinal })
    const results = Object.assign([result], { length: 1 })
    this.onresult?.({
      resultIndex: 0,
      results: results as unknown as SpeechRecognitionResultListLike,
    })
  }

  emitError(error: string): void {
    this.onerror?.({ error })
    this.onend?.()
  }
}

interface FakeUtterance {
  text: string
  lang: string
  rate: number
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
}

let utterances: FakeUtterance[] = []
let speechSynthesis: {
  speak: ReturnType<typeof vi.fn>
  cancel: ReturnType<typeof vi.fn>
}

function installSpeechRecognition(): void {
  FakeSpeechRecognition.instances = []
  Object.defineProperty(window, 'SpeechRecognition', {
    configurable: true,
    writable: true,
    value: FakeSpeechRecognition,
  })
  Object.defineProperty(window, 'webkitSpeechRecognition', {
    configurable: true,
    writable: true,
    value: undefined,
  })
}

function removeSpeechRecognition(): void {
  Object.defineProperty(window, 'SpeechRecognition', {
    configurable: true,
    writable: true,
    value: undefined,
  })
  Object.defineProperty(window, 'webkitSpeechRecognition', {
    configurable: true,
    writable: true,
    value: undefined,
  })
}

function installSpeechSynthesis(): void {
  utterances = []

  class FakeSpeechSynthesisUtterance implements FakeUtterance {
    text: string
    lang = ''
    rate = 1
    onend: (() => void) | null = null
    onerror: ((event: { error: string }) => void) | null = null

    constructor(text: string) {
      this.text = text
      utterances.push(this)
    }
  }

  speechSynthesis = {
    speak: vi.fn((utterance: FakeUtterance) => {
      // Playback stays active until the user stops it or the hook cancels it.
      void utterance
    }),
    cancel: vi.fn(),
  }

  Object.defineProperty(window, 'SpeechSynthesisUtterance', {
    configurable: true,
    writable: true,
    value: FakeSpeechSynthesisUtterance,
  })
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    writable: true,
    value: speechSynthesis,
  })
}

function removeSpeechSynthesis(): void {
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    writable: true,
    value: undefined,
  })
  Object.defineProperty(window, 'SpeechSynthesisUtterance', {
    configurable: true,
    writable: true,
    value: undefined,
  })
}

async function renderAssistant(): Promise<void> {
  render(<AIAssistant />)
  await waitFor(() => {
    expect(mockGetAiModels).toHaveBeenCalledTimes(1)
  })
  await waitFor(() => {
    expect(screen.getByTestId('model-selector')).not.toBeDisabled()
  })
}

function chatInput(): HTMLTextAreaElement {
  return screen.getByPlaceholderText(
    'Ask about inventory, orders, invoices...',
  ) as HTMLTextAreaElement
}

async function ask(question: string, answer: string): Promise<void> {
  mockChat.mockResolvedValueOnce({
    answer,
    model: 'llama3.2',
    tool_calls: [],
  })

  fireEvent.change(chatInput(), { target: { value: question } })
  fireEvent.click(screen.getByLabelText('Send message'))
  await screen.findByText(answer)
}

describe('AIAssistant voice input', () => {
  beforeEach(() => {
    installSpeechRecognition()
    installSpeechSynthesis()
    mockGetAiModels.mockReset()
    mockSwitchAiModel.mockReset()
    mockChat.mockReset()
    mockGetAiModels.mockResolvedValue(modelsResponse)
  })

  it('starts recording, fills the input, allows edits, and sends through the existing chat', async () => {
    await renderAssistant()

    const mic = screen.getByTestId('voice-mic-button')
    expect(mic).toHaveAccessibleName('Start voice input')

    fireEvent.click(mic)

    const recognition = FakeSpeechRecognition.instances[0]
    expect(recognition).toBeDefined()
    expect(recognition.start).toHaveBeenCalledTimes(1)
    expect(recognition.interimResults).toBe(true)
    expect(screen.getByTestId('voice-status')).toHaveTextContent('Listening')
    expect(mic).toHaveAccessibleName('Stop voice input')

    act(() => {
      recognition.emitResult('How much free stock', false)
    })
    expect(chatInput()).toHaveValue('How much free stock')

    act(() => {
      recognition.emitResult(
        'How much free stock do we have for Hex Bolt M10?',
        true,
      )
    })
    expect(chatInput()).toHaveValue(
      'How much free stock do we have for Hex Bolt M10?',
    )
    // Recognition alone must never submit a question.
    expect(mockChat).not.toHaveBeenCalled()

    fireEvent.change(chatInput(), {
      target: { value: 'How much free stock for Hex Bolt M10?' },
    })
    expect(chatInput()).toHaveValue('How much free stock for Hex Bolt M10?')

    mockChat.mockResolvedValueOnce({
      answer: 'Voice answer',
      model: 'llama3.2',
      tool_calls: [],
    })

    fireEvent.click(screen.getByLabelText('Send message'))

    await waitFor(() => {
      expect(mockChat).toHaveBeenCalledTimes(1)
    })
    expect(mockChat).toHaveBeenCalledWith({
      question: 'How much free stock for Hex Bolt M10?',
      history: [],
    })
    expect(await screen.findByText('Voice answer')).toBeInTheDocument()
  })

  it('preserves typed text and appends recognised speech', async () => {
    await renderAssistant()

    fireEvent.change(chatInput(), { target: { value: 'Show me' } })
    fireEvent.click(screen.getByTestId('voice-mic-button'))

    act(() => {
      FakeSpeechRecognition.instances[0].emitResult('low stock items', true)
    })

    expect(chatInput()).toHaveValue('Show me low stock items')
  })

  it('shows a clear error when microphone permission is denied', async () => {
    await renderAssistant()

    fireEvent.click(screen.getByTestId('voice-mic-button'))
    act(() => {
      FakeSpeechRecognition.instances[0].emitError('not-allowed')
    })

    expect(screen.getByTestId('voice-error')).toHaveTextContent(
      'Microphone access was blocked',
    )
    expect(chatInput()).toHaveValue('')
    expect(mockChat).not.toHaveBeenCalled()
  })

  it('reports when no speech was detected', async () => {
    await renderAssistant()

    fireEvent.click(screen.getByTestId('voice-mic-button'))
    fireEvent.click(screen.getByTestId('voice-mic-button'))

    expect(screen.getByTestId('voice-error')).toHaveTextContent(
      'No speech was detected',
    )
  })

  it('disables the microphone when speech recognition is unsupported', async () => {
    removeSpeechRecognition()
    await renderAssistant()

    const mic = screen.getByTestId('voice-mic-button')
    expect(mic).toBeDisabled()
    expect(mic).toHaveAttribute(
      'title',
      'Voice input is not supported in this browser',
    )
  })
})

describe('AIAssistant voice playback', () => {
  beforeEach(() => {
    installSpeechRecognition()
    installSpeechSynthesis()
    mockGetAiModels.mockReset()
    mockSwitchAiModel.mockReset()
    mockChat.mockReset()
    mockGetAiModels.mockResolvedValue(modelsResponse)
  })

  it('reads the actual assistant response and stops on a second click', async () => {
    await renderAssistant()
    await ask('List warehouses', 'There are two warehouses in the ERP.')

    const speak = screen.getByTestId('voice-speak-button')
    fireEvent.click(speak)

    expect(utterances).toHaveLength(1)
    expect(utterances[0].text).toBe('There are two warehouses in the ERP.')
    expect(speak).toHaveAttribute('aria-pressed', 'true')
    expect(speak).toHaveAccessibleName('Stop reading response aloud')
    expect(speechSynthesis.speak).toHaveBeenCalledTimes(1)

    const cancelsBeforeStop = speechSynthesis.cancel.mock.calls.length
    fireEvent.click(speak)

    expect(speechSynthesis.cancel.mock.calls.length).toBeGreaterThan(
      cancelsBeforeStop,
    )
    expect(speak).toHaveAttribute('aria-pressed', 'false')
    expect(speak).toHaveAccessibleName('Read response aloud')
  })

  it('stops the previous response before reading a new one', async () => {
    await renderAssistant()
    await ask('List warehouses', 'First answer about warehouses.')
    await ask('List products', 'Second answer about products.')

    const speakButtons = screen.getAllByTestId('voice-speak-button')
    expect(speakButtons).toHaveLength(2)

    fireEvent.click(speakButtons[0])
    expect(speakButtons[0]).toHaveAttribute('aria-pressed', 'true')

    const cancelsBeforeSwitch = speechSynthesis.cancel.mock.calls.length
    fireEvent.click(speakButtons[1])

    expect(speechSynthesis.cancel.mock.calls.length).toBeGreaterThan(
      cancelsBeforeSwitch,
    )
    expect(speakButtons[0]).toHaveAttribute('aria-pressed', 'false')
    expect(speakButtons[1]).toHaveAttribute('aria-pressed', 'true')
    expect(utterances[utterances.length - 1].text).toBe(
      'Second answer about products.',
    )
  })

  it('reports playback errors without breaking the message', async () => {
    await renderAssistant()

    speechSynthesis.speak.mockImplementation(
      (utterance: FakeUtterance) => {
        utterance.onerror?.({ error: 'synthesis-failed' })
      },
    )

    await ask('List warehouses', 'There are two warehouses in the ERP.')
    fireEvent.click(screen.getByTestId('voice-speak-button'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The response could not be read aloud',
    )
    expect(
      screen.getByText('There are two warehouses in the ERP.'),
    ).toBeInTheDocument()
  })

  it('disables the speaker when speech synthesis is unsupported', async () => {
    removeSpeechSynthesis()
    await renderAssistant()
    await ask('List warehouses', 'There are two warehouses in the ERP.')

    const speak = screen.getByTestId('voice-speak-button')
    expect(speak).toBeDisabled()
    expect(speak).toHaveAttribute(
      'title',
      'Speech playback is not supported in this browser',
    )
  })
})
