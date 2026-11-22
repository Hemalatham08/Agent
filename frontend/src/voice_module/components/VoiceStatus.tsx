import { CircleAlert, Mic } from 'lucide-react'

import type { SpeechRecognitionFailure } from '../hooks/useSpeechRecognition'

interface VoiceStatusProps {
  isListening: boolean
  error: SpeechRecognitionFailure | null
  onDismissError: () => void
}

/**
 * Compact recording/error indicator shown below the chat input.
 * Renders nothing when voice input is idle and healthy.
 */
export function VoiceStatus({
  isListening,
  error,
  onDismissError,
}: VoiceStatusProps) {
  if (error) {
    return (
      <div
        role="alert"
        data-testid="voice-error"
        className="mt-1.5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2"
      >
        <CircleAlert
          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-500"
          aria-hidden="true"
        />
        <p className="min-w-0 flex-1 break-words text-[10px] leading-4 text-rose-700">
          {error.message}
        </p>
        <button
          type="button"
          onClick={onDismissError}
          className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold text-rose-700 transition hover:bg-rose-100"
        >
          Dismiss
        </button>
      </div>
    )
  }

  if (!isListening) {
    return null
  }

  return (
    <div
      role="status"
      data-testid="voice-status"
      className="mt-1.5 flex items-center gap-2 rounded-xl border border-rose-100 bg-rose-50/70 px-3 py-2"
    >
      <span className="relative flex h-2 w-2 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" />
      </span>
      <Mic className="h-3 w-3 shrink-0 text-rose-500" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-[10px] font-medium text-rose-700">
        Listening… speak now, then click the microphone again to stop.
      </p>
    </div>
  )
}
