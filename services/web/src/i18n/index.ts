import { useCallback, useSyncExternalStore } from 'react'
import { es } from './es'

/**
 * Translations (Phase 5): what families and drivers read, in their
 * language. Decided by the product owner on 2026-10-07: Spanish first, for
 * the sign-in, family and driver screens; the staff console stays in
 * English. Spanish is marked as awaiting review by a fluent speaker
 * (docs/translation.md has the reviewer's checklist).
 *
 * Phrases are keyed by their English text, so English needs no file and
 * the code stays readable: `t('Sign in')`. Each other language is one file
 * typed `Record<Phrase, string>`, so a phrase missing from it fails the
 * build. `{name}` placeholders are filled from `t`'s second argument.
 *
 * The chosen language is remembered in this browser and, once signed in,
 * saved to the account (emails use it too). Before anyone has chosen, the
 * browser's own language decides. Staff accounts always see English.
 */

export type Phrase = keyof typeof es
export type Language = 'en' | 'es'
type Values = Record<string, string | number>

// Each language's own name, for the picker.
export const LANGUAGES: Record<Language, string> = { en: 'English', es: 'Español' }
// Languages a fluent speaker hasn't reviewed yet.
export const REVIEW_PENDING: ReadonlySet<Language> = new Set(['es'])
// For dates, times and speech.
export const LOCALES: Record<Language, string> = { en: 'en-US', es: 'es-US' }

const CATALOGS: Record<Exclude<Language, 'en'>, Record<Phrase, string>> = { es }
const STORAGE_KEY = 'isd.language'

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && value in LANGUAGES
}

/** The remembered choice, else the browser's first supported language. */
export function detectLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (isLanguage(saved)) return saved
  } catch {
    // Storage blocked: fall through to the browser's languages.
  }
  const wanted = typeof navigator === 'undefined' ? [] : (navigator.languages ?? [])
  for (const code of wanted) {
    const base = code.toLowerCase().split('-')[0]
    if (isLanguage(base)) return base
  }
  return 'en'
}

let chosen: Language = detectLanguage()
let englishOnly = false
const listeners = new Set<() => void>()

/** The language screens are shown in now. */
export function currentLanguage(): Language {
  return englishOnly ? 'en' : chosen
}

function changed() {
  if (typeof document !== 'undefined') {
    // WCAG 3.1.1: screen readers pronounce the page in its own language.
    document.documentElement.lang = currentLanguage()
  }
  listeners.forEach((listener) => listener())
}

export function chooseLanguage(language: Language) {
  chosen = language
  try {
    window.localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Not remembered in this browser; the account still keeps it.
  }
  changed()
}

/** The language chosen, whether or not this account shows it. */
export function chosenLanguage(): Language {
  return chosen
}

/** Staff accounts see English whatever was chosen (the staff console isn't translated). */
export function setEnglishOnly(flag: boolean) {
  if (flag !== englishOnly) {
    englishOnly = flag
    changed()
  }
}

/** For tests: back to English and nothing remembered. */
export function resetLanguageForTests() {
  chosen = 'en'
  englishOnly = false
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to forget.
  }
  changed()
}

export function translate(language: Language, phrase: Phrase, values?: Values): string {
  const template = language === 'en' ? phrase : CATALOGS[language][phrase]
  if (!values) return template
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? String(values[name]) : whole,
  )
}

/** Outside React (the API client): `phrase` in the current language. */
export function translateNow(phrase: Phrase, values?: Values): string {
  return translate(currentLanguage(), phrase, values)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The current language, and `t` for it; re-renders when it changes. */
export function useTranslation() {
  const language = useSyncExternalStore(subscribe, currentLanguage, currentLanguage)
  const tr = useCallback(
    (phrase: Phrase, values?: Values) => translate(language, phrase, values),
    [language],
  )
  return { language, locale: LOCALES[language], t: tr }
}

changed()
