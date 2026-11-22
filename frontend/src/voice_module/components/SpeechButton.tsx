import { Square, Volume2 } from 'lucide-react'

interface SpeechButtonProps {
  isSpeaking: boolean
  isSupported: boolean
  disabled?: boolean
  onClick: () => void
}

/**
 * Per-response speaker control. Clicking while speaking stops playback.
 */
export function SpeechButton({
  isSpeaking,
  isSupported,
  disabled = false,
  onClick,
}: SpeechButtonProps) {
  const label = !isSupported
    ? 'Speech playback is not supported in this browser'
    : isSpeaking
      ? 'Stop reading response aloud'
      : 'Read response aloud'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || !isSupported}
      aria-label={label}
      aria-pressed={isSpeaking}
      title={label}
      data-testid="voice-speak-button"
      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-100 disabled:cursor-not-allowed ${
        isSpeaking
          ? 'border-accent-200 bg-accent-50 text-accent-700'
          : 'border-slate-200 bg-white text-slate-500 hover:border-accent-200 hover:bg-accent-50 hover:text-accent-600'
      } ${disabled || !isSupported ? 'opacity-60' : ''}`}
    >
      {isSpeaking ? (
        <>
          <Square className="h-3 w-3 fill-current" aria-hidden="true" />
          <span>Stop</span>
          <span
            className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent-500"
            aria-hidden="true"
          />
        </>
      ) : (
        <>
          <Volume2 className="h-3 w-3" aria-hidden="true" />
          <span>Listen</span>
        </>
      )}
    </button>
  )
}
