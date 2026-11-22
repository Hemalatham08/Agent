export { MicrophoneButton } from './components/MicrophoneButton'
export { SpeechButton } from './components/SpeechButton'
export { VoiceStatus } from './components/VoiceStatus'
export { useSpeechRecognition } from './hooks/useSpeechRecognition'
export { useSpeechSynthesis } from './hooks/useSpeechSynthesis'
export {
  EMPTY_TRANSCRIPTION_MESSAGE,
  UNSUPPORTED_RECOGNITION_MESSAGE,
  describeRecognitionError,
  getSpeechRecognitionConstructor,
  isSpeechRecognitionSupported,
  normalizeRecognitionErrorCode,
} from './speech_to_text/speechRecognition'
export {
  EMPTY_SPEECH_MESSAGE,
  PLAYBACK_ERROR_MESSAGE,
  UNSUPPORTED_SYNTHESIS_MESSAGE,
  isSpeechSynthesisSupported,
  prepareSpeechText,
  splitSpeechText,
} from './text_to_speech/speechSynthesis'

export type {
  SpeechRecognitionErrorCode,
  SpeechRecognitionEventLike,
  SpeechRecognitionLike,
  SpeechRecognitionResultListLike,
} from './speech_to_text/speechRecognition'
export type {
  SpeechRecognitionFailure,
  SpeechTranscript,
  UseSpeechRecognitionOptions,
  UseSpeechRecognitionResult,
} from './hooks/useSpeechRecognition'
export type {
  SpeechPlaybackFailure,
  UseSpeechSynthesisOptions,
  UseSpeechSynthesisResult,
} from './hooks/useSpeechSynthesis'
