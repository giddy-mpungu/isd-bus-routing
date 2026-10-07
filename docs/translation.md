# Translation

What families and drivers read is translated; the staff console stays in
English. Decided by the product owner on 2026-10-07:

- **Spanish first**, built so another language is just one more phrase file.
- **Translated:** the sign-in, forgot-password, reset-password, two-step
  sign-in and Account pages; the Family page (with bus-time email setting,
  records download and correction requests); the driver's My day page and
  directions; "stop bus time emails"; and every email families get
  (password reset, account set-up, password changed, two-step changes,
  bus-time changes, answered correction requests).
- **Not translated:** the staff console (Schedule, Setup, Field trips,
  Templates, Reports, Users, My school). Staff accounts always see English,
  whatever language was chosen on the sign-in page.
- **Not translated, by nature:** text staff type themselves (announcements,
  road-closure notes, answers to correction requests, task instructions),
  names of people, schools and stops.
- Spanish ships **marked as awaiting review**: the language picker shows
  "Traducción pendiente de revisión", and Spanish emails end with a line
  saying the translation is waiting for review.

## How it works

| | Web (`services/web`) | API (`services/api`) |
|---|---|---|
| Phrase file | `src/i18n/es.ts` | `src/isd_api/i18n/es.py` |
| Core | `src/i18n/index.ts` (`useTranslation`, `translateNow`) | `src/isd_api/i18n/__init__.py` (`tr`, `translate_message`) |
| Completeness check | the build: a phrase used in code but missing from `es.ts` is a type error; `i18n.test.ts` fails on unused phrases or changed placeholders | `tests/test_i18n.py`: every phrase passed to `tr()` is in every catalog, placeholders match, no unused phrases |

Phrases are keyed by their **English text exactly as the code writes it**,
so English needs no file. `{name}` placeholders are filled in the same way
in every language and must be kept in the translation.

Which language is used:

1. On the web, the language chosen in the header picker, remembered in the
   browser (`localStorage` key `isd.language`) and, once signed in, saved to
   the account (`users.preferred_language`, `PUT /users/me/language`).
2. Before anyone chooses, the browser's own language decides.
3. Signing in shows the account's saved language; if the account has none
   yet, the one chosen before signing in is saved to it.
4. Every API request carries `Accept-Language`, so server messages (errors,
   "changes closed" notices, closure notes, directions from
   OpenRouteService) come back in the screen's language. An exception
   handler in `main.py` translates known error messages, including ones with
   values in them ("Use at least 8 characters").
5. Emails use the account's saved language, English if none. When staff
   create a family's account on the Users page, they can set the language of
   its emails ("Language for their emails").
6. The records download is a plain link, so it uses the account's saved
   language, else the browser's.

The page's `<html lang>` follows the language on screen (WCAG 3.1.1), and
read-aloud on the driver app uses a voice for that language.

## Adding a language

1. Web: copy `src/i18n/es.ts` to `src/i18n/<code>.ts`, type it
   `Record<Phrase, string>`, translate every value; add it to `LANGUAGES`
   (in its own name), `LOCALES`, `CATALOGS` and `REVIEW_PENDING` in
   `src/i18n/index.ts`.
2. API: copy `src/isd_api/i18n/es.py` to `<code>.py`, translate every value,
   add it to `LANGUAGES` and `CATALOGS` in `src/isd_api/i18n/__init__.py`.
3. Run the web build and tests and the API tests: they list anything
   missing.
4. Add it to `REVIEW_PENDING` on both sides until a fluent speaker has
   reviewed it (below); then take it out of both, which also drops the
   "waiting for review" line from its emails.

## Reviewer checklist (Spanish)

For a fluent speaker, ideally one who knows how the district writes to
families. Work from the two phrase files above; each line is
`'English': 'Spanish'`. Then sign in to the demo as a parent and a driver,
choose Español, and read the pages and emails as a family would.

- [ ] **Register:** formal *usted* throughout, neutral US-school Spanish
      (no regionalisms the district's families wouldn't use).
- [ ] **Terms used consistently:** *autobús*, *parada*, *recorrido* (a run),
      *viaje* (a family's ride), *excursión* (field trip), *despacho*
      (dispatch), *oficina de transporte*, *expediente* (the student's
      record), *inicio de sesión en dos pasos*.
- [ ] **Legs:** "AM"/"PM" are kept as written in some sentences ("el viaje AM
      de hoy"). Decide whether families would rather read *mañana*/*tarde*.
- [ ] **Driver status words** read well both as a badge and as a button. In
      particular "Arrived" is one phrase for both, translated *Llegada*;
      check it on the driver's next-step button.
- [ ] **"Something's wrong?"** (*¿Algo está mal?*) matches the records
      download's mention of it.
- [ ] **FERPA wording** in the correction emails and the records download
      (*audiencia*, *declaración*) matches how the district describes these
      rights in its own Spanish notices.
- [ ] **Emails:** subjects and greetings (*Hola, {name}:*), the review line
      at the end, and that every link still works.
- [ ] **Placeholders** (`{name}`, `{time}`, ...) still read naturally where
      they land in the sentence.
- [ ] **Nothing is cut off:** buttons and labels fit on a phone and on the
      driver's tablet (Spanish runs longer than English).
- [ ] Once done: remove `'es'` from `REVIEW_PENDING` in
      `services/web/src/i18n/index.ts` and `services/api/src/isd_api/i18n/__init__.py`,
      in one PR that names the reviewer.
