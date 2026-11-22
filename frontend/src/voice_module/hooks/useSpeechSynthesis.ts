import { useCallback, useEffect, useRef, useState } from 'react'

import {
  EMPTY_SPEECH_MESSAGE,
  PLAYBACK_ERROR_MESSAGE,
  UNSUPPORTED_SYNTHESIS_MESSAGE,
  isSpeechSynthesisSupported,
  prepareSpeechText,
  splitSpeechText,
} from '../text_to_speech/speechSynthesis'

export interface SpeechPlaybackFailure {
  message: string
  /** Assistant response that produced the error, when known. */
  responseId: string | null
}

export interface UseSpeechSynthesisOptions {
  /** BCP-47 language tag. Defaults to the browser language. */
  lang?: string
}

export interface UseSpeechSynthesisResult {
  isSupported: boolean
  speakingId: string | null
  error: SpeechPlaybackFailure | null
  speak: (responseId: string, text: string) => void
  stop: () => void
  toggle: (responseId: string, text: string) => void
  clearError: () => void
}

function browserLanguage(): string {
  if (typeof navigator !== 'undefined' && navigator.language) {
    return navigator.language
  }
  return 'en-US'
}

/**
 * React binding for the browser Speech Synthesis API.
 *
 * Only one response can be read at a time: starting a new response cancels the
 * previous queue, and clicking the active response stops playback.
 */
export function useSpeechSynthesis(
  options: UseSpeechSynthesisOptions = {},
): UseSpeechSynthesisResult {
  const [isSupported] = useState(() => isSpeechSynthesisSupported())
  const [speakingId, setSpeakingId] = useState<string | null>(null)
  const [error, setError] = useState<SpeechPlaybackFailure | null>(null)

  const speakingIdRef = useRef<string | null>(null)
  const generationRef = useRef(0)
  const languageRef = useRef(options.lang ?? browserLanguage())

  useEffect(() => {
    languageRef.current = options.lang ?? browserLanguage()
  }, [options.lang])

  const stop = useCallback(() => {
    generationRef.current += 1
    speakingIdRef.current = null
    setSpeakingId(null)

    if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel()
      } catch {
        // Ignore cancellation failures from the browser API.
      }
    }
  }, [])

  const speak = useCallback(
    (responseId: string, text: string) => {
      if (!isSupported) {
        setError({
          message: UNSUPPORTED_SYNTHESIS_MESSAGE,
          responseId,
        })
        return
      }

      const speechText = prepareSpeechText(text)
      if (!speechText) {
        setError({
          message: EMPTY_SPEECH_MESSAGE,
          responseId,
        })
        return
      }

      generationRef.current += 1
      const generation = generationRef.current

      try {
        window.speechSynthesis.cancel()
      } catch {
        // Starting a new utterance still supersedes any previous queue.
      }

      setError(null)
      speakingIdRef.current = responseId
      setSpeakingId(responseId)

      const chunks = splitSpeechText(speechText)

      const speakChunk = (index: number) => {
        if (generationRef.current !== generation) {
          return
        }

        if (index >= chunks.length) {
          speakingIdRef.current = null
          setSpeakingId(null)
          return
        }

        const utterance = new SpeechSynthesisUtterance(chunks[index])
        utterance.lang = languageRef.current
        utterance.rate = 1

        utterance.onend = () => {
          speakChunk(index + 1)
        }

        utterance.onerror = (event) => {
          if (
            event.error === 'canceled' ||
            event.error === 'interrupted' ||
            generationRef.current !== generation
          ) {
            return
          }

          speakingIdRef.current = null
          setSpeakingId(null)
          setError({
            message: PLAYBACK_ERROR_MESSAGE,
            responseId,
          })
        }

        window.speechSynthesis.speak(utterance)
      }

      speakChunk(0)
    },
    [isSupported],
  )

  const toggle = useCallback(
    (responseId: string, text: string) => {
      if (speakingIdRef.current === responseId) {
        stop()
        return
      }
      speak(responseId, text)
    },
    [speak, stop],
  )

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  useEffect(() => {
    return () => {
      generationRef.current += 1
      speakingIdRef.current = null

      if (typeof window !== 'undefined' && window.speechSynthesis) {
        try {
          window.speechSynthesis.cancel()
        } catch {
          // Ignore teardown failures from the browser API.
        }
      }
    }
  }, [])

  return {
    isSupported,
    speakingId,
    error,
    speak,
    stop,
    toggle,
    clearError,
  }
}
