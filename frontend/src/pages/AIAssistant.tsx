import {
  ArrowRight,
  Bot,
  CircleAlert,
  Cpu,
  Database,
  Info,
  LoaderCircle,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Sparkles,
  UserRound,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { AiModelSelector } from '../components/ai/AiModelSelector'
import { AssistantResponse } from '../components/ai/AssistantResponse'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { API_BASE_URL, aiModelLabel, erpApi } from '../services/api'
import type {
  AiModelInfo,
  ChatMessage,
  ChartSpec,
  ToolCallResult,
} from '../services/api'
import {
  MicrophoneButton,
  SpeechButton,
  VoiceStatus,
  useSpeechRecognition,
  useSpeechSynthesis,
} from '../voice_module'

const suggestedQuestions = [
  'How much free stock do we have for Hex Bolt M10?',
  'Which products are below their reorder level?',
  'Show me pending sales orders for Sri Venkateswara Engineering.',
  'Which purchase orders are delayed?',
  'What dispatch issues need attention today?',
  'How much is outstanding across unpaid invoices?',
]

const tools = [
  'Low-stock lookup',
  'Product search',
  'Inventory by warehouse',
  'Pending sales',
  'Pending purchases',
  'Dispatch issues',
  'Quality issues',
  'Unpaid invoices',
]

// Chat entries carry their own generation duration so every assistant message
// keeps its timing for the lifetime of the current session.
interface ChatEntry extends ChatMessage {
  durationMs?: number
  toolCalls?: ToolCallResult[]
  charts?: ChartSpec[]
  question?: string
}

function formatDurationSeconds(durationMs: number): string {
  return (durationMs / 1000).toFixed(2)
}

export default function AIAssistant() {
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [providers, setProviders] = useState<AiModelInfo[]>([])
  const [activeModelInfo, setActiveModelInfo] = useState<AiModelInfo | null>(null)
  const [isModelsLoading, setIsModelsLoading] = useState(true)
  const [isSwitchingModel, setIsSwitchingModel] = useState(false)
  const [modelError, setModelError] = useState<string | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)
  const chatScrollRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const voiceInputBaseRef = useRef('')

  const {
    isSupported: isVoiceInputSupported,
    isListening: isListeningForVoice,
    error: voiceInputError,
    start: startVoiceInput,
    stop: stopVoiceInput,
    resetError: resetVoiceInputError,
  } = useSpeechRecognition({
    onTranscript: ({ transcript }) => {
      const spoken = transcript.trim()
      const base = voiceInputBaseRef.current
      setInput(base && spoken ? `${base} ${spoken}` : spoken || base)
    },
  })

  const {
    isSupported: isSpeechPlaybackSupported,
    speakingId,
    error: speechPlaybackError,
    toggle: toggleSpeechPlayback,
  } = useSpeechSynthesis()

  const loadModels = useCallback(async () => {
    try {
      const response = await erpApi.getAiModels()
      setProviders(response.providers)
      setActiveModelInfo(response.active)
      setModelError(null)
    } catch (requestError) {
      setModelError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not load AI models.',
      )
    } finally {
      setIsModelsLoading(false)
    }
  }, [])

  useEffect(() => {
    // Provider status comes from the backend, so this effect synchronises with
    // an external system. The state updates happen after the request resolves.
    // oxlint-disable-next-line react/set-state-in-effect
    void loadModels()
  }, [loadModels])

  useEffect(() => {
    const scrollContainer = chatScrollRef.current

    if (!scrollContainer) {
      return
    }

    // Only scroll the conversation panel, not the page. Using scrollIntoView
    // here would also scroll the whole page and hide the chat panel at high
    // browser zoom levels.
    scrollContainer.scrollTo({
      top: scrollContainer.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, isLoading, error])

  async function submitQuestion(rawQuestion: string) {
    const question = rawQuestion.trim()

    if (!question || isLoading) {
      return
    }

    if (isListeningForVoice) {
      stopVoiceInput()
    }

    const history: ChatMessage[] = messages
      .slice(-20)
      .map(({ role, content }) => ({ role, content }))

    // Measure the full user-perceived request: backend processing plus any ERP
    // tool execution that happens before the answer comes back.
    const startedAt = performance.now()

    setMessages((current) => [...current, { role: 'user', content: question }])
    setInput('')
    setError(null)
    setIsLoading(true)

    try {
      const response = await erpApi.chat({ question, history })
      const durationMs = performance.now() - startedAt
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: response.answer,
          durationMs,
          toolCalls: response.tool_calls,
          charts: response.charts,
          question,
        },
      ])
      setModel(response.model)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not reach the AI service.',
      )
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitQuestion(input)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submitQuestion(input)
    }
  }

  function handleVoiceToggle() {
    if (isListeningForVoice) {
      stopVoiceInput()
      inputRef.current?.focus()
      return
    }

    // Preserve any text the user typed before dictating; recognised speech is
    // appended to it and remains fully editable before sending.
    voiceInputBaseRef.current = input.trim()
    startVoiceInput()
  }

  async function handleModelSwitch(provider: string) {
    if (
      !provider ||
      provider === activeModelInfo?.provider ||
      isSwitchingModel
    ) {
      return
    }

    setIsSwitchingModel(true)
    setModelError(null)

    try {
      const switched = await erpApi.switchAiModel(provider)
      setActiveModelInfo(switched)
      setModel(switched.model)
      await loadModels()
    } catch (requestError) {
      setModelError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not switch AI models.',
      )
    } finally {
      setIsSwitchingModel(false)
    }
  }

  const hasProviderIssue =
    modelError !== null || activeModelInfo?.available === false
  const isConnected =
    activeModelInfo?.available === true ||
    (activeModelInfo === null && model !== null && error === null)
  const statusLabel = isLoading
    ? 'Thinking...'
    : error
      ? 'Connection issue'
      : isSwitchingModel
        ? 'Switching model...'
        : activeModelInfo?.available === false
          ? 'Provider unavailable'
          : activeModelInfo?.available
            ? `Connected · ${aiModelLabel(activeModelInfo)}`
            : model
              ? `Connected · ${model}`
              : isModelsLoading
                ? 'Checking models...'
                : 'Ready'

  return (
    <div className="flex min-h-0 flex-col">
      <PageHeader
        className="mb-3 gap-2 sm:mb-4"
        title="AI Assistant"
        description="An ERP-aware copilot that answers natural-language questions using live business data."
        eyebrow="iFive Copilot"
        actions={
          <>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold ${
                error || hasProviderIssue
                  ? 'border-rose-200 bg-rose-50 text-rose-700'
                  : isLoading
                    ? 'border-amber-200 bg-amber-50 text-amber-700'
                    : isConnected
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : 'border-slate-200 bg-white text-slate-500'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  error || hasProviderIssue
                    ? 'bg-rose-500'
                    : isLoading
                      ? 'animate-pulse bg-amber-500'
                      : isConnected
                        ? 'bg-emerald-500'
                        : 'bg-slate-400'
                }`}
              />
              {statusLabel}
            </span>
            <button
              type="button"
              onClick={() => setIsSidebarOpen((open) => !open)}
              aria-expanded={isSidebarOpen}
              aria-controls="assistant-sidebar"
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
            >
              {isSidebarOpen ? (
                <PanelRightClose className="h-3.5 w-3.5" />
              ) : (
                <PanelRightOpen className="h-3.5 w-3.5" />
              )}
              {isSidebarOpen ? 'Hide Sidebar' : 'Show Sidebar'}
            </button>
          </>
        }
      />

      <div
        className={`grid grid-cols-1 gap-4 transition-[grid-template-columns,gap] duration-300 ease-out xl:items-start ${
          isSidebarOpen
            ? 'xl:grid-cols-[minmax(0,3fr)_minmax(0,1fr)] xl:gap-5'
            : 'xl:grid-cols-[minmax(0,1fr)_0fr] xl:gap-0'
        }`}
      >
        <Card className="flex h-[clamp(24rem,70dvh,44rem)] min-w-0 flex-col overflow-hidden xl:h-[calc(100dvh-14rem)] xl:max-h-[52rem] xl:min-h-[30rem]">
          <div className="flex shrink-0 items-center gap-3 border-b border-slate-100 px-5 py-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-navy-900 text-white">
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900">iFive Copilot</p>
              <p className="text-[11px] text-slate-400">
                ERP assistant powered by local AI models
              </p>
            </div>
            <div className="ml-auto flex min-w-0 justify-end">
              <AiModelSelector
                providers={providers}
                activeModel={activeModelInfo}
                isModelsLoading={isModelsLoading}
                isSwitching={isSwitchingModel}
                onSelect={handleModelSwitch}
              />
            </div>
          </div>

          {modelError ? (
            <div
              role="alert"
              data-testid="model-error"
              className="flex items-start gap-2 border-b border-amber-100 bg-amber-50 px-4 py-2.5"
            >
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="min-w-0 flex-1 break-words text-[11px] leading-5 text-amber-800">
                {modelError}
              </p>
              <button
                type="button"
                onClick={() => setModelError(null)}
                className="shrink-0 rounded-lg px-2 py-1 text-[10px] font-semibold text-amber-700 transition hover:bg-amber-100"
              >
                Dismiss
              </button>
            </div>
          ) : null}

          <div
            ref={chatScrollRef}
            className="scrollbar-thin min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50/40 p-4 sm:p-5"
          >
            {messages.length === 0 && !isLoading ? (
              <div className="flex h-full min-h-0 flex-col items-center justify-center px-4 py-6 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-50 text-accent-600 sm:h-14 sm:w-14">
                  <Sparkles className="h-6 w-6 sm:h-7 sm:w-7" />
                </div>
                <p className="mt-3 text-sm font-semibold text-slate-800">
                  Ask about your ERP data
                </p>
                <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                  Query inventory, sales orders, purchase orders, dispatch exceptions,
                  quality results, and outstanding invoices in plain language.
                </p>
                <p className="mt-3 text-[10px] font-medium text-slate-400">
                  Pick a suggested question or type your own below.
                </p>
              </div>
            ) : (
              <>
                {messages.map((message, index) =>
                  message.role === 'user' ? (
                    <div
                      key={`user-${index}`}
                      className="flex items-start justify-end gap-3"
                    >
                      <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-navy-900 px-4 py-3 shadow-sm">
                        <p className="whitespace-pre-wrap break-words text-xs leading-5 text-white">
                          {message.content}
                        </p>
                      </div>
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-200 text-slate-600">
                        <UserRound className="h-4 w-4" />
                      </div>
                    </div>
                  ) : (
                    <div
                      key={`assistant-${index}`}
                      className="flex items-start gap-3"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-600 text-white">
                        <Sparkles className="h-4 w-4" />
                      </div>
                      <div className="flex min-w-0 max-w-[85%] flex-col items-start gap-1.5">
                        <div
                          data-testid="assistant-bubble"
                          className="rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 shadow-sm"
                        >
                          <AssistantResponse
                            content={message.content}
                            toolCalls={message.toolCalls}
                            charts={message.charts}
                            question={message.question}
                          />
                        </div>
                        {typeof message.durationMs === 'number' ? (
                          <p
                            data-testid="response-duration"
                            className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500"
                          >
                            <span aria-hidden="true">⏱️</span>
                            <span>
                              Response generated in{' '}
                              {formatDurationSeconds(message.durationMs)} seconds
                            </span>
                          </p>
                        ) : null}
                        <SpeechButton
                          isSpeaking={speakingId === `assistant-${index}`}
                          isSupported={isSpeechPlaybackSupported}
                          onClick={() =>
                            toggleSpeechPlayback(
                              `assistant-${index}`,
                              message.content,
                            )
                          }
                        />
                        {speechPlaybackError?.responseId ===
                        `assistant-${index}` ? (
                          <p
                            role="alert"
                            className="break-words text-[10px] leading-4 text-rose-600"
                          >
                            {speechPlaybackError.message}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  ),
                )}

                {isLoading && (
                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-600 text-white">
                      <Sparkles className="h-4 w-4" />
                    </div>
                    <div className="flex items-center gap-2 rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
                      <LoaderCircle className="h-3.5 w-3.5 animate-spin text-accent-600" />
                      <span className="text-xs text-slate-500">
                        Querying ERP data...
                      </span>
                    </div>
                  </div>
                )}

                {error && (
                  <div className="flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5">
                    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] font-semibold text-rose-700">
                        Could not get an answer
                      </p>
                      <p className="mt-0.5 break-words text-[11px] leading-5 text-rose-600">
                        {error}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setError(null)}
                      className="shrink-0 rounded-lg px-2 py-1 text-[10px] font-semibold text-rose-600 transition hover:bg-rose-100"
                    >
                      Dismiss
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="shrink-0 border-t border-slate-100 bg-white p-3 sm:p-4">
            <form
              onSubmit={handleSubmit}
              className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2"
            >
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                placeholder="Ask about inventory, orders, invoices..."
                className="max-h-20 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-xs text-slate-700 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:text-slate-400"
              />
              <MicrophoneButton
                isListening={isListeningForVoice}
                isSupported={isVoiceInputSupported}
                disabled={isLoading}
                onClick={handleVoiceToggle}
              />
              <button
                type="submit"
                disabled={isLoading || !input.trim()}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-600 text-white transition hover:bg-accent-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
                aria-label="Send message"
              >
                {isLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </form>
            <VoiceStatus
              isListening={isListeningForVoice}
              error={voiceInputError}
              onDismissError={resetVoiceInputError}
            />
            <p className="mt-1.5 flex items-center justify-center gap-1.5 text-center text-[10px] text-slate-400">
              <Database className="h-3 w-3" />
              Answers are generated from ERP records returned by backend tools.
            </p>
          </div>
        </Card>

        <div
          id="assistant-sidebar"
          aria-hidden={!isSidebarOpen}
          inert={!isSidebarOpen}
          className={`flex min-w-0 flex-col gap-4 transition-[opacity,transform] duration-300 ease-out xl:gap-5 ${
            isSidebarOpen
              ? 'opacity-100'
              : 'max-xl:hidden xl:pointer-events-none xl:max-h-0 xl:overflow-hidden xl:translate-x-2 xl:opacity-0'
          }`}
        >
          <Card className="flex flex-col">
            <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
              <MessageSquare className="h-3.5 w-3.5 shrink-0 text-accent-600" />
              <h2 className="min-w-0 text-[11px] font-semibold text-slate-700">
                Suggested questions
              </h2>
              <span
                className="ml-auto inline-flex shrink-0 text-slate-400"
                title="Ask in plain language. The agent selects an ERP data tool and grounds the answer in live records."
              >
                <Info className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="sr-only">
                  How it works: ask in plain language. The agent selects an ERP data
                  tool and grounds the answer in live records.
                </span>
              </span>
            </div>
            <div className="space-y-0.5 p-1.5">
              {suggestedQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => {
                    if (isListeningForVoice) {
                      stopVoiceInput()
                    }
                    setInput(question)
                    inputRef.current?.focus()
                  }}
                  disabled={isLoading}
                  className="group flex w-full items-start gap-1.5 rounded-lg px-2 py-1.5 text-left text-[11px] leading-4 text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ArrowRight className="mt-0.5 h-2.5 w-2.5 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-accent-500" />
                  <span>{question}</span>
                </button>
              ))}
            </div>
          </Card>

          <Card className="flex flex-col">
            <CardHeader
              title="Backend status"
              description="Live integration"
              icon={Database}
            />
            <div className="space-y-3 px-5 pb-4">
              <div
                className={`flex items-center gap-2 rounded-xl px-3 py-2.5 ${
                  error || hasProviderIssue ? 'bg-rose-50' : 'bg-emerald-50'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    error || hasProviderIssue ? 'bg-rose-500' : 'bg-emerald-500'
                  }`}
                />
                <span
                  className={`text-[11px] font-semibold ${
                    error || hasProviderIssue
                      ? 'text-rose-700'
                      : 'text-emerald-700'
                  }`}
                >
                  {isModelsLoading
                    ? 'Checking AI providers...'
                    : activeModelInfo?.available === false
                      ? 'Provider unavailable'
                      : error
                        ? 'Last request failed'
                        : activeModelInfo
                          ? 'Provider connected'
                          : 'Provider status unknown'}
                </span>
              </div>
              {activeModelInfo?.reason && !activeModelInfo.available ? (
                <p className="break-words text-[10px] leading-4 text-rose-600">
                  {activeModelInfo.reason}
                </p>
              ) : null}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  API base URL
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-slate-600">
                  {API_BASE_URL}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Provider
                </p>
                <p className="mt-1 flex items-center gap-1.5 break-all font-mono text-[10px] text-slate-600">
                  <Cpu className="h-3 w-3 shrink-0 text-slate-400" />
                  {activeModelInfo
                    ? aiModelLabel(activeModelInfo)
                    : 'Configured by backend'}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Active model
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-slate-600">
                  {activeModelInfo?.model ?? model ?? 'Configured by backend'}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Provider URL
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-slate-600">
                  {activeModelInfo?.base_url ?? 'Not reported'}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Available data tools
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {tools.map((tool) => (
                    <span
                      key={tool}
                      className="rounded-md bg-slate-100 px-2 py-1 text-[9px] font-semibold text-slate-500"
                    >
                      {tool}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
