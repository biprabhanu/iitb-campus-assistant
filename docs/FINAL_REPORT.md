# CampusPilot: final report

IE624 student prototype. Not an official IIT Bombay service. Checked on 27 Nov 2026, against `main`.

Status words: `implemented_and_tested` (tested, and checked live where it applies), `implemented_not_tested`, `blocked`, `needs_human_review`.

## Feature status

| Feature | Status | Evidence | Known limitations |
|---|---|---|---|
| Public Q&A with citations (local Gemma) | implemented_and_tested | `make acceptance`, 25 questions: 96% expected behaviour, 75% expected source cited (`docs/EVAL.md`) | The index covers 44 documents from 9 approved sources. The hostel rules PDF is scanned, so it is link only. |
| Public Q&A, hosted (Groq, own key) | implemented_and_tested | Live Render API, 25 questions: 68% expected behaviour, 12% expected source cited, 0 errors, first token median 1.8 s (`docs/EVAL.md`, Hosted) | The prompts are tuned for Gemma. Hosted answers often have no citation, and Moodle questions ask a clarifying question instead of showing cards. This is the first thing to tune. |
| Hosted deploy (Vercel UI, Render API) | implemented_and_tested | `make smoke-hosted` passes 6 of 6 checks. `/v1/status` reports `deploy_mode: hosted` and `index: release` | Render's free plan sleeps, so the first request can take about 60 s. The UI shows "Waking the server". |
| Bring your own key, plus friendly errors | implemented_and_tested | pytest and Playwright smoke. 401 `MODEL_KEY_REQUIRED` | Groq is the only provider tested. Gemini, OpenAI and OpenRouter are `not_tested` (no key available). |
| Hosted has no connector routes | implemented_and_tested | Live probe: `/v1/connectors*` and `/v1/calendar/events` return 404. `connectors: []` | None |
| Moodle deadlines (iCal link) | implemented_and_tested | `make moodle-check`: connected, 2 deadlines in the next 14 days | Calendar-export mode has no course list. Moodle content is never sent to an LLM. |
| Webmail, read-only (IMAP) | implemented_and_tested | Live: latest and unread mail cards. `BODY.PEEK` leaves mail unread. 32 routing tests | Login is the LDAP ID plus an SSO access token. Needs the campus network or VPN, and local mode only. |
| Event detection to Google Calendar "Add" | implemented_and_tested | Live: one Add to the primary calendar gave `created`. A second click gave `already_exists` | Events are created only on click. Detection with Gemma is time-boxed. |
| ASC timetable, current courses, registration, profile | implemented_and_tested | Live `make asc-check`: 14 slots, 8 current courses, registration closed (8 courses), 6 of 6 profile fields | Needs the campus network or VPN. The registration page with the window open has not been seen live (`needs_human_review`). |
| ASC offered courses and offering history | implemented_and_tested | Live: IE Autumn 2025 returns 34 rows with slot and room. IE Autumn 2026 is empty because it is not yet published | The Referer change for Running Courses is not isolated as the cause (`needs_human_review`). |
| ASC course details and prerequisites | implemented_and_tested | Live: the IE 101 detail page has a title, 6 credits and a 792-character syllabus. The Prereq table gives rule strings such as "A OR B" | `newallCourse.jsp` is only a department picker, so the syllabus comes from the course-detail Description row. |
| ASC "Scholarship month view" (fees) | implemented_and_tested | Live: the "Fees Status/Scholarship" link goes to a scholarship-payment month picker. The tool says there is no fee table | There are no fee dues to show. Students check dues on ASC. |
| Privacy routing for personal ASC data | implemented_and_tested | 70 routing tests: personal ASC tools only with the local model. A cloud model gets a refusal line | None |
| Fresh clone | implemented_and_tested | In a temp clone with no `.env`: `make setup`, `make test` (581 and 59), `docker build`, and `make mock-dev` (mock status, UI 200, streamed chat with sources) | None |

## Privacy and safety (checked on 27 Nov 2026)

- **Connectors are local only.** Webmail, ASC and Google Calendar never run in hosted mode, which the live 404 probe confirms.
- **Logins and storage:**
  - Logins are kept in the macOS Keychain.
  - Webmail is read-only.
  - ASC is read-only, uses GET only, and has an allowlist.
  - Grades, SPI/CPI, bank, payment, feedback and form pages are never opened.
- **Personal data and models:**
  - Personal mail and ASC data go only to the local Gemma.
  - Moodle content goes to no model.
  - Personal cards are built from templates, so the model sees only counts.
- **Repository sweep:**
  - `make secrets-check` passes. The key and token grep finds only the fake values in tests.
  - There are no roll numbers, names, emails or campus IPs in tracked files.
  - `.env`, `*.db`, `data/raw/`, `data/processed/` and the Google client JSON are gitignored.
  - The ASC fixtures are synthetic.

## Known limitations

1. Hosted answer quality is behind local Gemma on citations. The prompts need tuning for the Groq models.
2. Several ASC layouts were mapped from one student's session. Other programs or an open registration window may differ.
3. The connectors need the IITB campus network or VPN, and macOS (Keychain).
4. This is a student prototype. Answers can be wrong, so check the cited official page.
