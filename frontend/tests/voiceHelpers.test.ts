import { describe, expect, it } from 'vitest'

import {
  describeRecognitionError,
  normalizeRecognitionErrorCode,
  prepareSpeechText,
  splitSpeechText,
} from '../src/voice_module'

describe('prepareSpeechText', () => {
  it('removes markdown formatting and reads table values without pipes', () => {
    const content = [
      '### Warehouses',
      '',
      '| Name | Code |',
      '| --- | --- |',
      '| Main Warehouse | WH001 |',
      '| Secondary Warehouse | WH002 |',
    ].join('\n')

    const speech = prepareSpeechText(content)

    expect(speech).not.toContain('|')
    expect(speech).not.toContain('###')
    expect(speech).toContain('Warehouses')
    expect(speech).toContain('Main Warehouse, WH001')
    expect(speech).toContain('Secondary Warehouse, WH002')
  })

  it('drops fenced code blocks and emphasis markers', () => {
    const speech = prepareSpeechText(
      '**Important** result.\n```json\n{"secret": true}\n```',
    )

    expect(speech).toBe('Important result.')
  })

  it('returns an empty string for blank content', () => {
    expect(prepareSpeechText('')).toBe('')
    expect(prepareSpeechText('   \n  ')).toBe('')
  })
})

describe('splitSpeechText', () => {
  it('keeps short answers in a single chunk', () => {
    expect(splitSpeechText('Short answer.')).toEqual(['Short answer.'])
  })

  it('splits long answers without losing text', () => {
    const sentence = 'This warehouse holds stainless steel fasteners for orders. '
    const text = sentence.repeat(12).trim()
    const chunks = splitSpeechText(text, 120)

    expect(chunks.length).toBeGreaterThan(1)
    expect(chunks.every((chunk) => chunk.length <= 120)).toBe(true)
    expect(chunks.join(' ')).toBe(text)
  })
})

describe('recognition error mapping', () => {
  it('recognises known browser error codes', () => {
    expect(normalizeRecognitionErrorCode('not-allowed')).toBe('not-allowed')
    expect(normalizeRecognitionErrorCode('no-speech')).toBe('no-speech')
    expect(normalizeRecognitionErrorCode('something-new')).toBe('unknown')
  })

  it('returns actionable messages for permission and microphone failures', () => {
    expect(describeRecognitionError('not-allowed')).toContain(
      'Allow microphone permissions',
    )
    expect(describeRecognitionError('audio-capture')).toContain(
      'No microphone was found',
    )
    expect(describeRecognitionError('no-speech')).toContain(
      'No speech was detected',
    )
  })
})
