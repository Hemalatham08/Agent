/**
 * Browser Speech Recognition (STT) capability detection and error mapping.
 *
 * This module intentionally contains no React code. It normalises the
 * vendor-prefixed Web Speech API surface used by Chrome, Edge, and Safari.
 */

export interface SpeechRecognitionAlternativeLike {
  transcript: string
  confidence: number
}

export interface SpeechRecognitionResultLike {
  readonly isFinal: boolean
  readonly length: number
  readonly [index: number]: SpeechRecognitionAlternativeLike
}

export interface SpeechRecognitionResultListLike {
  readonly length: number
  readonly [index: number]: SpeechRecognitionResultLike
}

export interface SpeechRecognitionEventLike {
  readonly resultIndex: number
  readonly results: SpeechRecognitionResultListLike
}

export interface SpeechRecognitionErrorEventLike {
  readonly error: string
  readonly message?: string
}

export interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  onstart: (() => void) | null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

export type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

export type SpeechRecognitionErrorCode =
  | 'not-allowed'
  | 'service-not-allowed'
  | 'audio-capture'
  | 'network'
  | 'no-speech'
  | 'aborted'
  | 'language-not-supported'
  | 'unknown'

export const UNSUPPORTED_RECOGNITION_MESSAGE =
  'Voice input is not supported in this browser. Try Chrome, Edge, or Safari.'

export const EMPTY_TRANSCRIPTION_MESSAGE =
  'No speech was detected. Click the microphone and try again.'

interface SpeechRecognitionWindow {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

export function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') {
    return null
  }

  const candidate = window as unknown as SpeechRecognitionWindow
  return (
    candidate.SpeechRecognition ??
    candidate.webkitSpeechRecognition ??
    null
  )
}

export function isSpeechRecognitionSupported(): boolean {
  return getSpeechRecognitionConstructor() !== null
}

export function normalizeRecognitionErrorCode(
  code: string,
): SpeechRecognitionErrorCode {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
    case 'audio-capture':
    case 'network':
    case 'no-speech':
    case 'aborted':
    case 'language-not-supported':
      return code
    default:
      return 'unknown'
  }
}

export function describeRecognitionError(
  code: SpeechRecognitionErrorCode,
): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone access was blocked. Allow microphone permissions in your browser and try again.'
    case 'audio-capture':
      return 'No microphone was found. Connect a microphone and try again.'
    case 'network':
      return 'The speech recognition service is unavailable. Check your connection and try again.'
    case 'no-speech':
      return EMPTY_TRANSCRIPTION_MESSAGE
    case 'aborted':
      return 'Voice input was cancelled.'
    case 'language-not-supported':
      return 'Your browser does not support speech recognition for this language.'
    default:
      return 'Voice input could not be completed. Please try again.'
  }
}
