import { afterEach, describe, expect, it } from 'vitest'
import { es } from './es'
import {
  chooseLanguage,
  currentLanguage,
  detectLanguage,
  setEnglishOnly,
  translate,
  translateNow,
  type Phrase,
} from '.'

// The app's own source, to check every phrase is still used.
const SOURCES = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../i18n/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const PLACEHOLDER = /\{(\w+)\}/g

function placeholders(text: string): string[] {
  return [...text.matchAll(PLACEHOLDER)].map((m) => m[1]).sort()
}

function quoted(phrase: string): string[] {
  return [`'${phrase}'`, `"${phrase}"`, `'${phrase.replace(/'/g, "\\'")}'`]
}

afterEach(() => {
  setEnglishOnly(false)
  chooseLanguage('en')
})

describe('the Spanish phrase file', () => {
  it('keeps every placeholder', () => {
    for (const [phrase, translated] of Object.entries(es)) {
      expect(placeholders(translated), phrase).toEqual(placeholders(phrase))
    }
  })

  it('holds no phrase the app no longer uses', () => {
    const code = Object.values(SOURCES).join('\n')
    const unused = Object.keys(es).filter((phrase) => !quoted(phrase).some((q) => code.includes(q)))
    expect(unused).toEqual([])
  })
})

describe('translating', () => {
  it('fills placeholders, in English and Spanish', () => {
    const phrase: Phrase = 'Bus due at {stop} around {time}'
    expect(translate('en', phrase, { stop: 'Elm St', time: '07:45' })).toBe(
      'Bus due at Elm St around 07:45',
    )
    expect(translate('es', phrase, { stop: 'Elm St', time: '07:45' })).toBe(
      'El autobús llega a Elm St alrededor de las 07:45',
    )
  })

  it('follows the chosen language, and marks the page with it', () => {
    chooseLanguage('es')
    expect(currentLanguage()).toBe('es')
    expect(translateNow('Sign in')).toBe('Iniciar sesión')
    expect(document.documentElement.lang).toBe('es')
    expect(window.localStorage.getItem('isd.language')).toBe('es')
  })

  it('shows staff English whatever was chosen', () => {
    chooseLanguage('es')
    setEnglishOnly(true)
    expect(currentLanguage()).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    setEnglishOnly(false)
    expect(currentLanguage()).toBe('es')
  })

  it('starts from the remembered choice, else the browser', () => {
    window.localStorage.removeItem('isd.language')
    Object.defineProperty(window.navigator, 'languages', {
      value: ['es-MX', 'en-US'],
      configurable: true,
    })
    try {
      expect(detectLanguage()).toBe('es')
      window.localStorage.setItem('isd.language', 'en')
      expect(detectLanguage()).toBe('en')
    } finally {
      // Back to the browser's own value.
      delete (window.navigator as { languages?: unknown }).languages
    }
  })
})
