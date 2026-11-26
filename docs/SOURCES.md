# Sources

CampusPilot answers only from the pages listed here. The list lives in
[`data/sources/registry.csv`](../data/sources/registry.csv), which is the only copy. The audit
of each row (checked 2026-11-26) is in [`data/sources/AUDIT.md`](../data/sources/AUDIT.md).

Handling values: `ingest` means fetched, parsed and searchable. `link_only` means the app shows the
official link but never fetches the content. `blocked` and `needs_review` are not used by any row today.

## Source table

Counts are indexed documents and chunks from the audit. A "document" is a page or a same-host PDF one level deep.

| ID | Title | Issuer | Tier | Handling | Reason | Docs / chunks |
|---|---|---|---|---|---|---|
| SRC-ACAD-CAL | Academic Calendar and Timetable | Academic Office | 1 | ingest | Public calendar and timetable pages and PDFs (one PDF had no text) | 10 / 70 |
| SRC-UG-ENTRANTS | Information for UG New Entrants 2026-27 | Academic Office | 1 | ingest | Audience limited to `ug_entrants_2026_27`. Four linked PDFs returned 404 and four had no text | 18 / 145 |
| SRC-PG-PHD-ENTRANTS | Information for PG/Ph.D. New Entrants 2026-27 | Academic Office | 1 | ingest | Title and cohort confirmed. Audience `pg_phd_entrants` | 6 / 23 |
| SRC-DOSA-RULES | Code of Conduct (DoSA web page) | Dean of Student Affairs | 1 | ingest | Official DoSA page | 3 / 19 |
| SRC-DOSA-CODE-PDF | Code of Conduct (PDF) | Dean of Student Affairs | 1 | ingest | Official text PDF | 1 / 8 |
| SRC-HOSTEL-RULES | Hostel Rules and Regulations (PDF) | DoSA / Hostel authority | 1 | link_only | Changed from ingest. The PDF is scanned with no text layer and there is no OCR in v1, so it cannot be cited. Kept as an official link | 0 / 0 |
| SRC-STUDENT-AFFAIRS | Student Affairs Office | Student Affairs Office | 1 | ingest | Official office page. One linked PDF returned 404 | 2 / 11 |
| SRC-CONTACT | Contact Us | IIT Bombay | 1 | ingest | Institute contact page (text only) | 2 / 23 |
| SRC-GYMKHANA | Students' Gymkhana | Students' Gymkhana | 2 | ingest | Student body. Never outranks tier 1. No robots.txt (404), nothing disallowed | 1 / 8 |
| SRC-HOSTEL-FAQ | Hostel FAQs and Guidelines | Hostel Affairs Council | 2 | ingest | Secondary guidance from a student body. Answers come from the page's FAQ data | 1 / 28 |
| SRC-ASC | Academic Systems Portal (ASC) | Academic Systems | 1 | link_only | Login portal. Link only, no content fetched | 0 / 0 |
| SRC-MOODLE | Moodle | IIT Bombay | 1 | link_only | Login portal. Data is read only through the Moodle API tools, not by crawling | 0 / 0 |
| SRC-SUPPORT | IIT Bombay Support Portal | IIT Bombay services | 1 | link_only | Hostel maintenance and IT ticket portal. Link only | 0 / 0 |
| SRC-INSTIAPP | InstiApp Campus Map | InstiApp | 2 | link_only | Third-party student app. Link only | 0 / 0 |

**Totals (audit, 2026-11-26):** 9 rows `ingest` with 44 documents and 335 chunks indexed. Six extra
PDFs failed text extraction (scanned or empty) and are stored as `failed`, never indexed. 5 rows
`link_only`, 0 `blocked`, 0 `needs_review`.

## How we fetch responsibly

- **Identify ourselves.** Every request sends the User-Agent `CampusPilot-student-prototype (IE624 course project)`.
- **Respect robots.txt.** It is read once per host and cached. A rule that disallows a path skips that
  fetch and marks the source as blocked by robots. A missing robots.txt (404) allows everything. The
  audit found no rule that excludes the fetched paths.
- **Go slowly.** At most one request every 2 seconds per host. `make ingest` is slow on purpose.
- **Follow PDFs one level deep.** Only PDFs linked from the source page, on the same host, are fetched.
  At most 25 PDFs per source. Each response is capped at 30 MB.
- **Store and reuse.** Raw downloads are kept in `data/raw/` (gitignored). `make reindex` rebuilds the
  index from them without fetching again.
- **Retry only on network trouble.** If a page fails from the Mac with a network-style error, the
  fetcher may retry it through an SSH alias named `passpoli`. Robots-blocked pages are never retried.
- **Stay inside the approved list.** Only `ingest` rows are fetched. Pages that only need a login
  (ASC, Moodle, Support) are never crawled.

## Authority rule

- **Tier 1 beats tier 2.** Tier 1 is the office responsible for the topic (Academic Office,
  DoSA, Student Affairs). Tier 2 is student-body guidance (Gymkhana, Hostel Affairs Council) and
  third-party apps (InstiApp). In search, tier-1 results get a 1.25 score boost.
- **Authority is topic-specific.** A tier-2 page can be the best source for something a tier-1
  office does not publish, such as a student-run FAQ.
- **Conflicts are shown, not picked silently.** When sources disagree, the answer should show both
  and point to the responsible office. The ranking boost is the code-level mechanism. Nothing in
  the code silently drops the lower-tier source.
- **Student-body pages never override an office.** This is the rule behind the tier 2 label.
