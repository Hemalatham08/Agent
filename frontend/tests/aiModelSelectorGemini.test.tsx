import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AiModelSelector } from '../src/components/ai/AiModelSelector'
import type { AiModelInfo } from '../src/services/api'

const ollama: AiModelInfo = {
  provider: 'ollama',
  model: 'llama3.2',
  base_url: 'http://127.0.0.1:11434',
  available: true,
  active: true,
  reason: null,
}

const llamacpp: AiModelInfo = {
  provider: 'llamacpp',
  model: 'qwen3-1.7b',
  base_url: 'http://127.0.0.1:11435',
  available: true,
  active: false,
  reason: null,
}

const gemini: AiModelInfo = {
  provider: 'gemini',
  model: 'gemini-3.5-flash-lite',
  base_url: 'https://generativelanguage.googleapis.com',
  available: true,
  active: false,
  reason: null,
}

function renderSelector(
  providers: AiModelInfo[],
  activeProvider = 'ollama',
  onSelect = vi.fn(),
) {
  const active =
    providers.find((provider) => provider.provider === activeProvider) ??
    providers[0]

  render(
    <AiModelSelector
      providers={providers}
      activeModel={active}
      isModelsLoading={false}
      isSwitching={false}
      onSelect={onSelect}
    />,
  )

  return onSelect
}

function openModelMenu() {
  fireEvent.click(screen.getByTestId('model-selector'))
  return screen.getByRole('dialog', { name: 'Select AI Model' })
}

describe('AiModelSelector Gemini provider', () => {
  it('shows Gemini as a third option when the backend reports it configured and available', () => {
    renderSelector([ollama, llamacpp, gemini])
    const dialog = openModelMenu()

    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(3)
    expect(options[0]).toHaveAccessibleName(/Ollama — Llama 3\.2/)
    expect(options[1]).toHaveAccessibleName(/Qwen3 1\.7B/)
    expect(options[2]).toHaveAccessibleName(/Gemini \(Google\)/)
    expect(options[2]).toHaveAttribute('aria-selected', 'false')

    expect(
      screen.getByText(
        /gemini · https:\/\/generativelanguage\.googleapis\.com/,
      ),
    ).toBeInTheDocument()
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(dialog).toBeInTheDocument()
  })

  it('keeps the existing two options when the backend omits Gemini', () => {
    renderSelector([ollama, llamacpp])
    openModelMenu()

    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(
      screen.queryByRole('option', { name: /Gemini/ }),
    ).not.toBeInTheDocument()
  })

  it('hides Gemini when the backend reports it as unavailable', () => {
    renderSelector([
      ollama,
      llamacpp,
      { ...gemini, available: false, reason: 'GEMINI_API_KEY is not set' },
    ])
    openModelMenu()

    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(
      screen.queryByRole('option', { name: /Gemini/ }),
    ).not.toBeInTheDocument()
  })

  it('switches to Gemini through the existing provider callback', () => {
    const onSelect = renderSelector([ollama, llamacpp, gemini])
    openModelMenu()

    fireEvent.click(screen.getByRole('option', { name: /Gemini \(Google\)/ }))

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('gemini')
    expect(screen.queryByTestId('model-dropdown')).not.toBeInTheDocument()
  })

  it('shows the Gemini label and active state when Gemini is active', () => {
    renderSelector(
      [
        { ...ollama, active: false },
        llamacpp,
        { ...gemini, active: true },
      ],
      'gemini',
    )

    expect(screen.getByTestId('active-model')).toHaveTextContent(
      'Gemini (Google)',
    )
    expect(screen.getByTestId('model-selector')).toHaveAttribute(
      'data-active-provider',
      'gemini',
    )
    expect(screen.getByTestId('model-connection-status')).toHaveTextContent(
      'Connected',
    )
  })
})
