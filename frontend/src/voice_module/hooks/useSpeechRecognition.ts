import { useCallback, useEffect, useRef, useState } from 'react'

import {
  EMPTY_TRANSCRIPTION_MESSAGE,
  UNSUPPORTED_RECOGNITION_MESSAGE,
  describeRecognitionError,
  getSpeechRecognitionConstructor,
  isSpeechRecognitionSupported,
  normalizeRecognitionErrorCode,
} from '../speech_to_text/speechRecognition'
import type {
  SpeechRecognitionErrorCode,
  SpeechRecognitionLike,
} from '../speech_to_text/speechRecognition'

export interface SpeechTranscript {
  /** Final plus interim text captured in the current session. */
  transcript: string
  finalTranscript: string
  interimTranscript: string
  /** True when the latest result was finalised by the browser. */
  isFinal: boolean
}

export interface SpeechRecognitionFailure {
  code: SpeechRecognitionErrorCode | 'unsupported' | 'empty'
  message: string
}

export interface UseSpeechRecognitionOptions {
  /** BCP-47 language tag. Defaults to the browser language. */
  lang?: string
  /** Keep listening after a pause. Defaults to true. */
  continuous?: boolean
  /** Called on every recognised phrase. Does not submit the question. */
  onTranscript?: (result: SpeechTranscript) => void
}

export interface UseSpeechRecognitionResult {
  isSupported: boolean
  isListening: boolean
  interimTranscript: string
  error: SpeechRecognitionFailure | null
  /** Returns false when recognition is unsupported or cannot start. */
  start: () => boolean
  stop: () => void
  toggle: () => void
  resetError: () => void
}

function browserLanguage(): string {
  if (typeof navigator !== 'undefined' && navigator.language) {
    return navigator.language
  }
  return 'en-US'
}

/**
 * React binding for the Web Speech API.
 *
 * Recognised text is delivered through ``onTranscript`` only. The caller owns
 * the chat input and decides when (or whether) to submit, so voice input never
 * sends a question automatically.
 */
export function useSpeechRecognition(
  options: UseSpeechRecognitionOptions = {},
): UseSpeechRecognitionResult {
  const [isSupported] = useState(() => isSpeechRecognitionSupported())
  const [isListening, setIsListening] = useState(false)
  const [interimTranscript, setInterimTranscript] = useState('')
  const [error, setError] = useState<SpeechRecognitionFailure | null>(null)

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const finalTranscriptRef = useRef('')
  const interimTranscriptRef = useRef('')
  const lastSpokenTextRef = useRef('')
  const errorRef = useRef<SpeechRecognitionFailure | null>(null)
  const callbackRef = useRef(options.onTranscript)
  const languageRef = useRef(options.lang ?? browserLanguage())
  const continuousRef = useRef(options.continuous ?? true)

  useEffect(() => {
    callbackRef.current = options.onTranscript
  }, [options.onTranscript])

  useEffect(() => {
    languageRef.current = options.lang ?? browserLanguage()
  }, [options.lang])

  useEffect(() => {
    continuousRef.current = options.continuous ?? true
  }, [options.continuous])

  const reportError = useCallback((failure: SpeechRecognitionFailure) => {
    errorRef.current = failure
    setError(failure)
  }, [])

  const resetError = useCallback(() => {
    errorRef.current = null
    setError(null)
  }, [])

  const stop = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) {
      setIsListening(false)
      return
    }

    try {
      recognition.stop()
    } catch {
      try {
        recognition.abort()
      } catch {
        recognitionRef.current = null
        setIsListening(false)
      }
    }
  }, [])

  const start = useCallback((): boolean => {
    if (!isSupported) {
      reportError({
        code: 'unsupported',
        message: UNSUPPORTED_RECOGNITION_MESSAGE,
      })
      return false
    }

    if (recognitionRef.current) {
      return true
    }

    const Recognition = getSpeechRecognitionConstructor()
    if (!Recognition) {
      reportError({
        code: 'unsupported',
        message: UNSUPPORTED_RECOGNITION_MESSAGE,
      })
      return false
    }

    const recognition = new Recognition()
    recognition.continuous = continuousRef.current
    recognition.interimResults = true
    recognition.lang = languageRef.current
    recognition.maxAlternatives = 1

    finalTranscriptRef.current = ''
    interimTranscriptRef.current = ''
    lastSpokenTextRef.current = ''
    errorRef.current = null
    setError(null)
    setInterimTranscript('')

    recognition.onstart = () => {
      setIsListening(true)
    }

    recognition.onresult = (event) => {
      let interim = ''

      for (
        let index = event.resultIndex;
        index < event.results.length;
        index += 1
      ) {
        const result = event.results[index]
        const alternative = result?.[0]
        const text = alternative?.transcript?.trim() ?? ''
        if (!text) {
          continue
        }

        if (result.isFinal) {
          finalTranscriptRef.current =
            `${finalTranscriptRef.current} ${text}`.trim()
        } else {
          interim = `${interim} ${text}`.trim()
        }
      }

      interimTranscriptRef.current = interim
      const finalText = finalTranscriptRef.current
      const spoken = `${finalText} ${interim}`.trim()
      lastSpokenTextRef.current = spoken
      setInterimTranscript(interim)

      callbackRef.current?.({
        transcript: spoken,
        finalTranscript: finalText,
        interimTranscript: interim,
        isFinal: interim.length === 0 && finalText.length > 0,
      })
    }

    recognition.onerror = (event) => {
      const code = normalizeRecognitionErrorCode(event.error)

      // The browser raises "aborted" during teardown and explicit stops.
      if (code === 'aborted') {
        return
      }

      reportError({
        code,
        message: describeRecognitionError(code),
      })
    }

    recognition.onend = () => {
      recognitionRef.current = null
      setIsListening(false)
      setInterimTranscript('')
      interimTranscriptRef.current = ''

      if (!lastSpokenTextRef.current && !errorRef.current) {
        reportError({
          code: 'empty',
          message: EMPTY_TRANSCRIPTION_MESSAGE,
        })
      }
    }

    recognitionRef.current = recognition
    setIsListening(true)

    try {
      recognition.start()
    } catch {
      recognitionRef.current = null
      setIsListening(false)
      reportError({
        code: 'unknown',
        message: describeRecognitionError('unknown'),
      })
      return false
    }

    return true
  }, [isSupported, reportError])

  const toggle = useCallback(() => {
    if (recognitionRef.current) {
      stop()
      return
    }
    start()
  }, [start, stop])

  useEffect(() => {
    return () => {
      const recognition = recognitionRef.current
      recognitionRef.current = null

      if (!recognition) {
        return
      }

      recognition.onstart = null
      recognition.onresult = null
      recognition.onerror = null
      recognition.onend = null

      try {
        recognition.abort()
      } catch {
        // Ignore teardown failures from the browser API.
      }
    }
  }, [])

  return {
    isSupported,
    isListening,
    interimTranscript,
    error,
    start,
    stop,
    toggle,
    resetError,
  }
}
