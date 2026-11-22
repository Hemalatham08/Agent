import {
  Check,
  ChevronDown,
  Cpu,
  LoaderCircle,
  Server,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type {
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import { createPortal } from 'react-dom'
import type { AiModelInfo } from '../../services/api'

interface AiModelSelectorProps {
  providers: AiModelInfo[]
  activeModel: AiModelInfo | null
  isModelsLoading: boolean
  isSwitching: boolean
  onSelect: (provider: string) => Promise<void> | void
}

interface ProviderMeta {
  name: string
  provider: string
  endpoint: string
  model: string
  Icon: LucideIcon
}

interface DropdownPosition {
  top: number
  left: number
  width: number
  maxHeight: number
  placement: 'top' | 'bottom'
}

const PROVIDER_ORDER = ['ollama', 'llamacpp', 'gemini'] as const

const PROVIDER_META: Record<string, ProviderMeta> = {
  ollama: {
    name: 'Ollama — Llama 3.2',
    provider: 'ollama',
    endpoint: 'http://127.0.0.1:11434',
    model: 'llama3.2',
    Icon: Server,
  },
  llamacpp: {
    name: 'Qwen3 1.7B',
    provider: 'llamacpp',
    endpoint: 'http://127.0.0.1:11435',
    model: 'qwen3-1.7b',
    Icon: Cpu,
  },
  gemini: {
    name: 'Gemini (Google)',
    provider: 'gemini',
    endpoint: 'https://generativelanguage.googleapis.com',
    model: 'gemini-3.5-flash-lite',
    Icon: Sparkles,
  },
}

function providerMeta(provider: string | null | undefined): ProviderMeta {
  if (provider && PROVIDER_META[provider]) {
    return PROVIDER_META[provider]
  }

  return {
    name: 'Select model',
    provider: 'provider',
    endpoint: '',
    model: '',
    Icon: Cpu,
  }
}

function availabilityLabel(
  provider: AiModelInfo,
  isModelsLoading: boolean,
  isSwitching: boolean,
): string {
  if (isModelsLoading) {
    return 'Checking...'
  }
  if (provider.active) {
    if (isSwitching) {
      return 'Switching...'
    }
    return provider.available ? 'Active · Connected' : 'Active · Unavailable'
  }
  return provider.available ? 'Available' : 'Unavailable'
}

function statusDotClass(
  provider: AiModelInfo,
  isModelsLoading: boolean,
): string {
  if (isModelsLoading) {
    return 'animate-pulse bg-slate-300'
  }
  if (provider.available) {
    return 'bg-emerald-500'
  }
  return provider.active ? 'bg-rose-500' : 'bg-slate-300'
}

function statusTextClass(
  provider: AiModelInfo,
  isModelsLoading: boolean,
): string {
  if (isModelsLoading) {
    return 'text-slate-400'
  }
  if (provider.available) {
    return 'text-emerald-600'
  }
  return provider.active ? 'text-rose-600' : 'text-slate-400'
}

export function AiModelSelector({
  providers,
  activeModel,
  isModelsLoading,
  isSwitching,
  onSelect,
}: AiModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [position, setPosition] = useState<DropdownPosition | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const headingId = useId()
  const listboxId = useId()

  // Keep the selector limited to the supported providers, in a stable order.
  // Gemini is only listed once the backend confirms it is configured and
  // reachable, so unconfigured installations look exactly as they did before.
  const orderedProviders = PROVIDER_ORDER.map((provider) =>
    providers.find((candidate) => candidate.provider === provider),
  )
    .filter((provider): provider is AiModelInfo => provider !== undefined)
    .filter(
      (provider) => provider.provider !== 'gemini' || provider.available,
    )

  const activeMeta = providerMeta(activeModel?.provider)
  const ActiveIcon = activeMeta.Icon
  const activeName = activeModel
    ? activeMeta.name
    : isModelsLoading
      ? 'Loading models…'
      : 'Select model'

  const activeUnavailable = activeModel?.available === false
  const badge = isSwitching
    ? {
        label: 'Switching',
        className: 'border-amber-200 bg-amber-50 text-amber-700',
        dot: 'animate-pulse bg-amber-500',
      }
    : isModelsLoading
      ? {
          label: 'Checking',
          className: 'border-slate-200 bg-white text-slate-500',
          dot: 'animate-pulse bg-slate-400',
        }
      : activeUnavailable
        ? {
            label: 'Unavailable',
            className: 'border-rose-200 bg-rose-50 text-rose-700',
            dot: 'bg-rose-500',
          }
        : activeModel?.available
          ? {
              label: 'Connected',
              className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
              dot: 'bg-emerald-500',
            }
          : {
              label: 'Unknown',
              className: 'border-slate-200 bg-white text-slate-500',
              dot: 'bg-slate-400',
            }

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) {
      return
    }

    const rect = trigger.getBoundingClientRect()
    const padding = 12
    const width = Math.max(
      180,
      Math.min(340, window.innerWidth - padding * 2),
    )
    const maxLeft = Math.max(padding, window.innerWidth - width - padding)
    const left = Math.max(padding, Math.min(rect.right - width, maxLeft))
    const spaceBelow = window.innerHeight - rect.bottom - padding
    const spaceAbove = rect.top - padding
    const placement =
      spaceBelow < 360 && spaceAbove > spaceBelow ? 'top' : 'bottom'
    const top = placement === 'bottom' ? rect.bottom + 8 : rect.top - 8
    const availableHeight =
      placement === 'bottom'
        ? window.innerHeight - top - padding
        : top - padding

    setPosition({
      top,
      left,
      width,
      maxHeight: Math.max(180, Math.min(440, availableHeight)),
      placement,
    })
  }, [])

  useEffect(() => {
    if (!isOpen) {
      return
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (
        triggerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) {
        return
      }
      setIsOpen(false)
    }

    function handleDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== 'Escape') {
        return
      }
      event.preventDefault()
      setIsOpen(false)
      triggerRef.current?.focus()
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleDocumentKeyDown)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    updatePosition()

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleDocumentKeyDown)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, updatePosition])

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const panel = panelRef.current
    if (!panel) {
      return
    }

    const options = Array.from(
      panel.querySelectorAll<HTMLButtonElement>('[role="option"]'),
    )
    const selected = panel.querySelector<HTMLButtonElement>(
      '[role="option"][aria-selected="true"]',
    )
    const target = selected ?? options[0]
    target?.focus()
  }, [isOpen])

  function openMenu() {
    if (isModelsLoading || isSwitching) {
      return
    }
    updatePosition()
    setIsOpen(true)
  }

  function closeMenu() {
    setIsOpen(false)
  }

  function toggleMenu() {
    if (isOpen) {
      closeMenu()
    } else {
      openMenu()
    }
  }

  function handleTriggerKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
  ) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!isOpen) {
        openMenu()
      }
    }
  }

  function handleListboxKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const panel = panelRef.current
    if (!panel) {
      return
    }

    const options = Array.from(
      panel.querySelectorAll<HTMLButtonElement>('[role="option"]'),
    )
    if (options.length === 0) {
      return
    }

    const currentIndex = options.indexOf(
      document.activeElement as HTMLButtonElement,
    )

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      options[(currentIndex + 1 + options.length) % options.length]?.focus()
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      options[(currentIndex - 1 + options.length) % options.length]?.focus()
    } else if (event.key === 'Home') {
      event.preventDefault()
      options[0]?.focus()
    } else if (event.key === 'End') {
      event.preventDefault()
      options[options.length - 1]?.focus()
    }
  }

  function handlePanelBlur(event: ReactFocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget as Node | null
    if (
      next &&
      (event.currentTarget.contains(next) || triggerRef.current?.contains(next))
    ) {
      return
    }
    setIsOpen(false)
  }

  function handleSelect(provider: AiModelInfo) {
    if (provider.provider === activeModel?.provider) {
      closeMenu()
      triggerRef.current?.focus()
      return
    }

    closeMenu()
    void onSelect(provider.provider)
  }

  return (
    <div className="relative flex items-center gap-2">
      <button
        ref={triggerRef}
        type="button"
        data-testid="model-selector"
        data-active-provider={activeModel?.provider ?? ''}
        aria-label={
          activeModel
            ? `Select AI model. Current model: ${activeMeta.name}, ${activeMeta.provider}.`
            : 'Select AI model'
        }
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
        disabled={isModelsLoading || isSwitching}
        onClick={toggleMenu}
        onKeyDown={handleTriggerKeyDown}
        className="group inline-flex h-9 min-w-0 items-center gap-2 rounded-xl border border-slate-200 bg-white px-2.5 text-left shadow-sm transition hover:border-slate-300 hover:bg-slate-50 focus-visible:border-accent-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600 transition group-hover:bg-slate-200">
          <ActiveIcon className="h-3.5 w-3.5" />
        </span>
        <span
          data-testid="active-model"
          className="max-w-28 truncate text-[11px] font-semibold text-slate-700 sm:max-w-36"
        >
          {activeName}
        </span>
        {isSwitching ? (
          <LoaderCircle
            className="h-3.5 w-3.5 shrink-0 animate-spin text-accent-600"
            aria-label="Switching model"
          />
        ) : (
          <ChevronDown
            className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${
              isOpen ? 'rotate-180' : ''
            }`}
          />
        )}
      </button>

      <span
        data-testid="model-connection-status"
        className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold ${badge.className}`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${badge.dot}`} />
        {badge.label}
      </span>

      {isOpen && position
        ? createPortal(
            <div
              ref={panelRef}
              role="dialog"
              aria-label="Select AI Model"
              data-testid="model-dropdown"
              style={{
                top: position.top,
                left: position.left,
                width: position.width,
                maxHeight: position.maxHeight,
                transform:
                  position.placement === 'top'
                    ? 'translateY(-100%)'
                    : undefined,
              }}
              className="fixed z-[70] overflow-y-auto rounded-2xl border border-slate-200/80 bg-white p-2 shadow-[0_24px_60px_-24px_rgba(15,23,42,0.45)]"
              onKeyDown={handleListboxKeyDown}
              onBlur={handlePanelBlur}
            >
              <p
                id={headingId}
                className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
              >
                Select AI Model
              </p>

              <div
                id={listboxId}
                role="listbox"
                aria-labelledby={headingId}
                className="space-y-1"
              >
                {orderedProviders.map((provider) => {
                  const meta = providerMeta(provider.provider)
                  const Icon = meta.Icon
                  const active = provider.provider === activeModel?.provider

                  return (
                    <button
                      key={provider.provider}
                      type="button"
                      role="option"
                      aria-selected={active}
                      data-testid={`model-option-${provider.provider}`}
                      onClick={() => handleSelect(provider)}
                      className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 ${
                        active
                          ? 'bg-sky-50 ring-1 ring-inset ring-sky-100'
                          : 'hover:bg-slate-50'
                      }`}
                    >
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                          active
                            ? 'bg-sky-100 text-sky-600'
                            : 'bg-slate-100 text-slate-500'
                        }`}
                      >
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span
                          className={`block truncate text-[11px] font-semibold ${
                            active ? 'text-sky-900' : 'text-slate-700'
                          }`}
                        >
                          {meta.name}
                        </span>
                        <span className="mt-0.5 block truncate text-[9px] text-slate-400">
                          {meta.provider} · {provider.base_url || meta.endpoint}
                        </span>
                      </span>
                      {active ? (
                        <>
                          <Check
                            className="h-4 w-4 shrink-0 text-sky-600"
                            aria-hidden="true"
                          />
                          <span className="sr-only">Active model</span>
                        </>
                      ) : null}
                    </button>
                  )
                })}
              </div>

              <div className="my-2 border-t border-slate-100" />

              <div className="rounded-xl bg-slate-50 px-2.5 py-2">
                <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                  Model status
                </p>
                <div className="mt-1.5 space-y-1.5">
                  {orderedProviders.map((provider) => {
                    const meta = providerMeta(provider.provider)

                    return (
                      <div
                        key={provider.provider}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="flex min-w-0 items-center gap-1.5">
                          <span
                            className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(
                              provider,
                              isModelsLoading,
                            )}`}
                          />
                          <span className="truncate text-[10px] font-medium text-slate-600">
                            {meta.name}
                          </span>
                        </span>
                        <span
                          className={`shrink-0 text-[9px] font-semibold ${statusTextClass(
                            provider,
                            isModelsLoading,
                          )}`}
                        >
                          {availabilityLabel(
                            provider,
                            isModelsLoading,
                            isSwitching,
                          )}
                        </span>
                      </div>
                    )
                  })}
                </div>
                {activeUnavailable && activeModel?.reason ? (
                  <p className="mt-2 break-words text-[9px] leading-4 text-rose-500">
                    {activeModel.reason}
                  </p>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
