import {
  ArrowRight,
  Bot,
  CircleAlert,
  Database,
  LoaderCircle,
  MessageSquare,
  Send,
  Sparkles,
  UserRound,
  Zap,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { API_BASE_URL, erpApi } from '../services/api'
import type { ChatMessage } from '../services/api'

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

export default function AIAssistant() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isLoading, error])

  async function submitQuestion(rawQuestion: string) {
    const question = rawQuestion.trim()

    if (!question || isLoading) {
      return
    }

    const history = messages.slice(-20)

    setMessages((current) => [...current, { role: 'user', content: question }])
    setInput('')
    setError(null)
    setIsLoading(true)

    try {
      const response = await erpApi.chat({ question, history })
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: response.answer },
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

  const isConnected = model !== null && error === null
  const statusLabel = isLoading
    ? 'Thinking...'
    : error
      ? 'Connection issue'
      : isConnected
        ? `Connected · ${model}`
        : 'Ready'

  return (
    <>
      <PageHeader
        title="AI Assistant"
        description="An ERP-aware copilot that answers natural-language questions using live business data."
        eyebrow="iFive Copilot"
        actions={
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold ${
              error
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
                error
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
        }
      />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_340px]">
        <Card className="flex min-h-[660px] flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-navy-900 text-white">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">iFive Copilot</p>
              <p className="text-[11px] text-slate-400">
                ERP assistant powered by local Ollama models
              </p>
            </div>
            <span className="ml-auto max-w-40 truncate rounded-full bg-slate-100 px-2.5 py-1 font-mono text-[10px] font-semibold text-slate-500">
              {model ?? 'Ollama'}
            </span>
          </div>

          <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto bg-slate-50/40 p-5">
            {messages.length === 0 && !isLoading ? (
              <div className="flex min-h-[420px] flex-col items-center justify-center px-6 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-50 text-accent-600">
                  <Sparkles className="h-7 w-7" />
                </div>
                <p className="mt-4 text-sm font-semibold text-slate-800">
                  Ask about your ERP data
                </p>
                <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                  Query inventory, sales orders, purchase orders, dispatch exceptions,
                  quality results, and outstanding invoices in plain language.
                </p>
                <p className="mt-4 text-[10px] font-medium text-slate-400">
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
                      <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
                        <p className="whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">
                          {message.content}
                        </p>
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

                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          <div className="border-t border-slate-100 bg-white p-4">
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
                className="max-h-24 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-xs text-slate-700 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:text-slate-400"
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
            <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[10px] text-slate-400">
              <Database className="h-3 w-3" />
              Answers are generated from ERP records returned by backend tools.
            </p>
          </div>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Suggested questions"
              description="Click a prompt to add it to the composer"
              icon={MessageSquare}
            />
            <div className="space-y-1 px-3 pb-4">
              {suggestedQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => {
                    setInput(question)
                    inputRef.current?.focus()
                  }}
                  disabled={isLoading}
                  className="group flex w-full items-start gap-2 rounded-xl px-2.5 py-2 text-left text-[11px] leading-5 text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ArrowRight className="mt-1 h-3 w-3 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-accent-500" />
                  <span>{question}</span>
                </button>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="How it works"
              description="Live agent workflow"
              icon={Zap}
            />
            <ol className="space-y-3 px-5 pb-5">
              {[
                'Ask a question in natural language.',
                'The agent selects an ERP data tool.',
                'Ollama grounds the answer in live records.',
              ].map((step, index) => (
                <li key={step} className="flex items-start gap-3">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-50 text-[10px] font-bold text-accent-700">
                    {index + 1}
                  </span>
                  <span className="text-[11px] leading-5 text-slate-600">{step}</span>
                </li>
              ))}
            </ol>
          </Card>

          <Card>
            <CardHeader
              title="Backend status"
              description="Live integration"
              icon={Database}
            />
            <div className="space-y-3 px-5 pb-5">
              <div
                className={`flex items-center gap-2 rounded-xl px-3 py-2.5 ${
                  error ? 'bg-rose-50' : 'bg-emerald-50'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    error ? 'bg-rose-500' : 'bg-emerald-500'
                  }`}
                />
                <span
                  className={`text-[11px] font-semibold ${
                    error ? 'text-rose-700' : 'text-emerald-700'
                  }`}
                >
                  {error ? 'Last request failed' : 'POST /chat connected'}
                </span>
              </div>
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
                  Active model
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-slate-600">
                  {model ?? 'Configured by backend'}
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
    </>
  )
}
