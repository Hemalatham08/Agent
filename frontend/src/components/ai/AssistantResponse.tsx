import { useMemo } from 'react'
import { buildErpTables, parseAnswerContent } from '../../lib/erpTables'
import type { ToolCallResult } from '../../services/api'
import { ErpDataTable } from './ErpDataTable'

interface AssistantResponseProps {
  content: string
  toolCalls?: ToolCallResult[]
  question?: string
}

/**
 * Renders an assistant answer as text plus tables.
 *
 * Markdown tables produced by the model are rendered directly. When the answer
 * contains no table, structured tables are derived from the actual read-only
 * ERP tool results returned by the backend for this response.
 */
export function AssistantResponse({
  content,
  toolCalls,
  question = '',
}: AssistantResponseProps) {
  const segments = useMemo(() => parseAnswerContent(content), [content])
  const hasMarkdownTable = segments.some((segment) => segment.type === 'table')

  const structuredTables = useMemo(
    () => (hasMarkdownTable ? [] : buildErpTables(toolCalls, question)),
    [hasMarkdownTable, toolCalls, question],
  )

  return (
    <div className="min-w-0">
      {segments.map((segment, index) =>
        segment.type === 'text' ? (
          <p
            key={`text-${index}`}
            className="whitespace-pre-wrap break-words text-xs leading-5 text-slate-700"
          >
            {segment.text}
          </p>
        ) : (
          <ErpDataTable key={segment.spec.id} spec={segment.spec} />
        ),
      )}

      {structuredTables.map((spec) => (
        <ErpDataTable key={spec.id} spec={spec} />
      ))}
    </div>
  )
}
