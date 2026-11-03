import {
  ArrowRight,
  Bot,
  CircleAlert,
  Database,
  LockKeyhole,
  MessageSquare,
  Send,
  Sparkles,
  UserRound,
  Zap,
} from 'lucide-react'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'

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
  return (
    <>
      <PageHeader
        title="AI Assistant"
        description="An ERP-aware copilot designed to answer natural-language questions using live business data."
        eyebrow="iFive Copilot"
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] font-semibold text-amber-700">
            <CircleAlert className="h-3.5 w-3.5" />
            Preview · POST /chat pending
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
            <span className="ml-auto rounded-full bg-slate-100 px-2.5 py-1 font-mono text-[10px] font-semibold text-slate-500">
              llama3.2
            </span>
          </div>

          <div className="flex items-start gap-2.5 border-b border-amber-100 bg-amber-50/70 px-5 py-3">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <p className="text-[11px] leading-5 text-amber-800">
              The backend does not expose <span className="font-mono">POST /chat</span> yet.
              This interface is prepared for that endpoint and currently runs in preview
              mode with sample content only.
            </p>
          </div>

          <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto bg-slate-50/40 p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-600 text-white">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-xs leading-5 text-slate-700">
                  Hello. I can help you investigate inventory, sales orders, purchase
                  orders, dispatch exceptions, quality results, and outstanding invoices
                  across ABC Fasteners &amp; Industrial Supplies.
                </p>
                <p className="mt-2 text-[10px] font-medium text-slate-400">
                  Sample assistant message
                </p>
              </div>
            </div>

            <div className="flex items-start justify-end gap-3">
              <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-navy-900 px-4 py-3 shadow-sm">
                <p className="text-xs leading-5 text-white">
                  Which products are below their reorder level right now?
                </p>
                <p className="mt-2 text-right text-[10px] font-medium text-slate-400">
                  Sample user question
                </p>
              </div>
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-200 text-slate-600">
                <UserRound className="h-4 w-4" />
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-600 text-white">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-xs leading-5 text-slate-700">
                  There are 6 low-stock records. Hex Bolt M10 is below its reorder level
                  in both warehouses, Hex Nut M10 in Secondary Warehouse, Machine Screw M6
                  in Main Warehouse, and Anchor Bolt M12 plus Hex Bolt M12 in Secondary
                  Warehouse.
                </p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-[9px] font-semibold text-slate-500">
                    search_products
                  </span>
                  <span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-[9px] font-semibold text-slate-500">
                    get_low_stock_products
                  </span>
                </div>
                <p className="mt-2 text-[10px] font-medium text-slate-400">
                  Sample response preview
                </p>
              </div>
            </div>
          </div>

          <div className="border-t border-slate-100 bg-white p-4">
            <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2">
              <textarea
                rows={1}
                disabled
                placeholder="Chat will be enabled when the backend exposes POST /chat..."
                className="max-h-24 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-xs text-slate-500 outline-none placeholder:text-slate-400"
              />
              <button
                type="button"
                disabled
                className="flex h-9 w-9 shrink-0 cursor-not-allowed items-center justify-center rounded-xl bg-slate-200 text-slate-400"
                aria-label="Send message (unavailable)"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[10px] text-slate-400">
              <LockKeyhole className="h-3 w-3" />
              Read-only preview. No chat request is sent.
            </p>
          </div>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Suggested questions"
              description="Prompts the copilot is designed to answer"
              icon={MessageSquare}
            />
            <div className="space-y-1 px-3 pb-4">
              {suggestedQuestions.map((question) => (
                <div
                  key={question}
                  className="group flex items-start gap-2 rounded-xl px-2.5 py-2 text-[11px] leading-5 text-slate-600 transition hover:bg-slate-50"
                >
                  <ArrowRight className="mt-1 h-3 w-3 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-accent-500" />
                  <span>{question}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="How it works"
              description="Agent workflow once chat is connected"
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
              description="Integration readiness"
              icon={Database}
            />
            <div className="space-y-3 px-5 pb-5">
              <div className="flex items-center gap-2 rounded-xl bg-rose-50 px-3 py-2.5">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                <span className="text-[11px] font-semibold text-rose-700">
                  POST /chat is not implemented
                </span>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  API base URL
                </p>
                <p className="mt-1 font-mono text-[10px] text-slate-600">
                  127.0.0.1:8000
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
