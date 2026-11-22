# Voice module

Frontend-only voice controls for the iFive ERP AI Assistant. The module uses
the browser's built-in Web Speech APIs; it does not call the backend, external
cloud services, or any paid APIs, and it does not change existing chat payloads
or responses.

## Structure

```
voice_module/
  speech_to_text/
    speechRecognition.ts   # vendor-prefixed API detection, error mapping
  text_to_speech/
    speechSynthesis.ts     # markdown-to-speech cleanup, chunking
  hooks/
    useSpeechRecognition.ts
    useSpeechSynthesis.ts
  components/
    MicrophoneButton.tsx
    SpeechButton.tsx
    VoiceStatus.tsx
  index.ts                 # public exports
  README.md
```

Tests live in `frontend/tests/voiceHelpers.test.ts` and
`frontend/tests/voiceModule.test.tsx`, following the project's existing test
location and Vitest configuration.

## Integration

Only `frontend/src/pages/AIAssistant.tsx` is wired to the module:

- `useSpeechRecognition` writes recognised text into the existing `input`
  state. The existing `submitQuestion` / Send handler remains the only way a
  question is sent.
- `useSpeechSynthesis` reads `message.content` from the assistant response that
  is already displayed. Tool metadata, durations, and hidden content are never
  passed to speech.
- No API request or response shapes were changed.

## Behaviour

### Speech to text

- Toggle with the microphone button next to the chat input.
- Live interim results appear in the input and remain editable.
- Typed text present before recording is preserved; recognised speech is
  appended to it.
- Recognition never submits automatically.
- Handled states: unsupported browser, permission denied, no microphone,
  network failure, no speech detected, user stop, and empty transcription.

### Text to speech

- Every assistant response has a `Listen` button.
- Clicking the active response again stops playback.
- Starting another response cancels the previous one, so audio never overlaps.
- Long answers are split into chunks to avoid browser cut-off.
- Markdown formatting, fenced blocks, and table separators are removed before
  speaking; table values are still read in order.
- Handled states: unsupported browser, empty response, and playback errors.

## Browser limitations

- Speech recognition is supported in Chrome, Edge, and Safari. Firefox does not
  currently expose the Web Speech recognition API, so the microphone button is
  disabled there.
- `webkitSpeechRecognition` is used automatically on Safari.
- Browser speech recognition may send audio to the browser vendor's speech
  service (for example, Chrome uses Google's service). This is a browser
  feature, not an application integration; the app itself has no external voice
  provider, key, or paid service.
- Speech synthesis availability and voice quality depend on the operating
  system and installed voices.
- Recognition requires a secure context: `https://` or `localhost`
  (`http://127.0.0.1` also works in Chromium browsers).
- Microphone permission must be granted in the browser; blocked permission
  shows an inline message with recovery guidance.

## Manual testing

1. Run `npm run dev` in `frontend/`.
2. Open the AI Assistant page.
3. Click the microphone, allow permission, and speak a question. Confirm the
   text appears in the input and can be edited.
4. Press Send and confirm the normal answer flow still works.
5. Click `Listen` under an assistant answer; click again to stop.
6. Play one answer, then another, and confirm the first stops.
7. Deny microphone permission and confirm the error message appears.
8. Use a browser without speech recognition (for example Firefox) and confirm
   the microphone button is disabled with a tooltip.

Run the automated checks with:

```
npm test
npm run lint
npm run build
```
