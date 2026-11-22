/**
 * Browser Speech Synthesis (TTS) helpers.
 *
 * The Web Speech Synthesis API reads text on the user's device. This module
 * turns assistant answers into clean, speakable chunks so markdown tables and
 * formatting are not read as raw technical characters.
 */

export const UNSUPPORTED_SYNTHESIS_MESSAGE =
  'Speech playback is not supported in this browser. Try Chrome, Edge, or Safari.'

export const EMPTY_SPEECH_MESSAGE =
  'There is no response text to read aloud.'

export const PLAYBACK_ERROR_MESSAGE =
  'The response could not be read aloud. Please try again.'

export function isSpeechSynthesisSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.speechSynthesis !== 'undefined' &&
    typeof window.SpeechSynthesisUtterance !== 'undefined'
  )
}

function isTableSeparator(line: string): boolean {
  return /^[|\s:-]+$/.test(line) && line.includes('-')
}

/**
 * Convert displayed answer content into natural speech.
 *
 * Fenced code, markdown table separators, and emphasis markers are removed.
 * Table pipes become commas so row values are still read in order.
 */
export function prepareSpeechText(text: string): string {
  if (!text) {
    return ''
  }

  const withoutFences = text.replace(/```[\s\S]*?```/g, ' ')
  const spokenLines: string[] = []

  for (const rawLine of withoutFences.split(/\r?\n/)) {
    const trimmed = rawLine.trim()
    if (!trimmed || isTableSeparator(trimmed)) {
      continue
    }

    const cleaned = trimmed
      .replace(/\|/g, ', ')
      .replace(/^#{1,6}\s*/, '')
      .replace(/^[>*+-]\s*/, '')
      .replace(/`/g, '')
      .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
      .replace(/\s*,\s*/g, ', ')
      .replace(/\s{2,}/g, ' ')
      .trim()

    if (cleaned) {
      spokenLines.push(cleaned)
    }
  }

  return spokenLines
    .join('. ')
    .replace(/\.(\s*\.)+/g, '.')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Split long answers into utterance-sized chunks.
 *
 * Some browsers stop long utterances early, so answers are split at sentence
 * boundaries and queued sequentially.
 */
export function splitSpeechText(text: string, maxLength = 220): string[] {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (!normalized) {
    return []
  }
  if (normalized.length <= maxLength) {
    return [normalized]
  }

  const chunks: string[] = []
  let remaining = normalized

  while (remaining.length > maxLength) {
    const window = remaining.slice(0, maxLength)
    let cut = Math.max(
      window.lastIndexOf('. '),
      window.lastIndexOf('! '),
      window.lastIndexOf('? '),
      window.lastIndexOf('; '),
    )

    if (cut < maxLength * 0.5) {
      cut = window.lastIndexOf(' ')
    }
    if (cut <= 0) {
      cut = maxLength - 1
    }

    chunks.push(remaining.slice(0, cut + 1).trim())
    remaining = remaining.slice(cut + 1).trim()
  }

  if (remaining) {
    chunks.push(remaining)
  }
  return chunks
}
