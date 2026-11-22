import { useMemo } from 'react'
import { buildErpTables, parseAnswerContent } from '../../lib/erpTables'
import type { ChartSpec, ToolCallResult } from '../../services/api'
import { ErpChart } from './ErpChart'
import { ErpDataTable } from './ErpDataTable'

interface AssistantResponseProps {
  content: string
  toolCalls?: ToolCallResult[]
  charts?: ChartSpec[]
  question?: string
}

/**
 * Renders an assistant answer as text plus charts and tables.
 *
 * Order: text, then charts (derived from read-only ERP tool output), then
 * tables. Markdown tables produced by the model are rendered inline. When the
 * answer contains no table, structured tables are derived from the actual
 * read-only ERP tool results returned by the backend for this response.
 */
export function AssistantResponse({
  content,
  toolCalls,
  charts = [],
  question = '',
}: AssistantResponseProps) {
  const segments = useMemo(() => parseAnswerContent(content), [content])
  const hasMarkdownTable = segments.some((segment) => segment.type === 'table')

  const textSegments = segments.filter((segment) => segment.type === 'text')
  const tableSegments = segments.filter((segment) => segment.type === 'table')

  const structuredTables = useMemo(
    () => (hasMarkdownTable ? [] : buildErpTables(toolCalls, question)),
    [hasMarkdownTable, toolCalls, question],
  )

  return (
    <div className="min-w-0">
      {textSegments.map((segment, index) => (
        <p
          key={`text-${index}`}
          className="whitespace-pre-wrap break-words text-xs leading-5 text-slate-700"
        >
          {segment.text}
        </p>
      ))}

      {charts.map((chart, index) => (
        <div key={`chart-${index}`} className="mt-4 mb-2">
          <ErpChart spec={chart} />
        </div>
      ))}

      {tableSegments.map((segment, index) => (
        <ErpDataTable key={`table-${index}`} spec={segment.spec} />
      ))}

      {structuredTables.map((spec) => (
        <ErpDataTable key={spec.id} spec={spec} />
      ))}
    </div>
  )
}
