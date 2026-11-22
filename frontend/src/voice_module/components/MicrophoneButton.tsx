import { Mic, MicOff, Square } from 'lucide-react'

interface MicrophoneButtonProps {
  isListening: boolean
  isSupported: boolean
  disabled?: boolean
  onClick: () => void
}

/**
 * Microphone control for the existing chat input.
 *
 * The button never submits a question; it only starts or stops recognition.
 */
export function MicrophoneButton({
  isListening,
  isSupported,
  disabled = false,
  onClick,
}: MicrophoneButtonProps) {
  const label = !isSupported
    ? 'Voice input is not supported in this browser'
    : isListening
      ? 'Stop voice input'
      : 'Start voice input'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || !isSupported}
      aria-label={label}
      aria-pressed={isListening}
      title={label}
      data-testid="voice-mic-button"
      className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-100 disabled:cursor-not-allowed ${
        isListening
          ? 'border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100'
          : 'border-slate-200 bg-white text-slate-500 hover:border-accent-200 hover:bg-accent-50 hover:text-accent-600'
      } ${disabled || !isSupported ? 'opacity-60' : ''}`}
    >
      {isListening ? (
        <span
          className="absolute inset-0 animate-ping rounded-xl bg-rose-400/30"
          aria-hidden="true"
        />
      ) : null}
      {!isSupported ? (
        <MicOff className="relative h-4 w-4" aria-hidden="true" />
      ) : isListening ? (
        <Square
          className="relative h-3 w-3 fill-current"
          aria-hidden="true"
        />
      ) : (
        <Mic className="relative h-4 w-4" aria-hidden="true" />
      )}
    </button>
  )
}
