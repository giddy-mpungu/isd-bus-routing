import { useAuth } from '../auth/AuthContext'
import * as api from '../api/client'
import {
  LANGUAGES,
  REVIEW_PENDING,
  chooseLanguage,
  isLanguage,
  useTranslation,
  type Language,
} from '../i18n'

/**
 * Choose the language for screens (and, once signed in, emails). Each
 * language is listed in its own name, so anyone can find theirs.
 */
export function LanguagePicker() {
  const { user } = useAuth()
  const { language, t } = useTranslation()

  function choose(value: string) {
    if (!isLanguage(value)) return
    chooseLanguage(value)
    if (user) api.setMyLanguage(value).catch(() => undefined)
  }

  return (
    <div className="language-picker">
      <label htmlFor="language-picker">{t('Language')}</label>
      <select
        id="language-picker"
        value={language}
        onChange={(event) => choose(event.target.value)}
      >
        {(Object.keys(LANGUAGES) as Language[]).map((code) => (
          <option key={code} value={code} lang={code}>
            {LANGUAGES[code]}
          </option>
        ))}
      </select>
      {REVIEW_PENDING.has(language) && (
        <span className="language-review">{t('Translation awaiting review')}</span>
      )}
    </div>
  )
}
