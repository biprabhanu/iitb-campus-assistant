# Source audit (checked 2026-11-26)

Method: robots.txt read per host; pages fetched from the Mac with the CampusPilot User-Agent, at most one request
per 2 s per host; `link_only` rows got a reachability HEAD only (no GET of ASC, Moodle or support pages).
Passpoli was not needed: every fetch worked from the Mac (`fetched_via` = mac for all rows).
"Docs / chunks" counts indexed documents (the page plus same-host PDFs one level deep) and their chunks.
Extra PDFs that failed extraction (scanned or empty) are stored with status=failed and never indexed.

| id | URL | HTTP | Title seen | robots | handling | reason | fetched_via | docs / chunks |
|---|---|---|---|---|---|---|---|---|
| SRC-ACAD-CAL | acad.iitb.ac.in/academics/calendar-and-timetable | 200 | Calendar and Timetable | allowed (Drupal default) | ingest | Academic Office, tier 1, public calendar and timetable PDFs (1 PDF had no text) | mac | 10 / 70 |
| SRC-UG-ENTRANTS | acad.iitb.ac.in/information-ug-new-entrants-2026-27 | 200 | Information for UG New Entrants 2026-27 | allowed | ingest | Cohort matches the registry; audience limited to ug_entrants_2026_27. 4 linked PDFs 404, 4 had no text | mac | 18 / 145 |
| SRC-PG-PHD-ENTRANTS | acad.iitb.ac.in/node/442 | 200 | Information for PG/Ph.D. New Entrants 2026-27 | allowed | ingest | Title and cohort confirmed (PG/Ph.D. new entrants, Autumn 2026-27); audience pg_phd_entrants | mac | 6 / 23 |
| SRC-DOSA-RULES | dosa.iitb.ac.in/code-of-conduct | 200 | Code of conduct | allowed | ingest | DoSA, tier 1 | mac | 3 / 19 |
| SRC-DOSA-CODE-PDF | dosa.iitb.ac.in/sites/default/files/codeofconduct.pdf | 200 | (PDF, no embedded title) | allowed | ingest | DoSA, tier 1, text PDF | mac | 1 / 8 |
| SRC-HOSTEL-RULES | dosa.iitb.ac.in/sites/default/files/hostelrulesregulations.pdf | 200 | (PDF, 3 pages) | allowed | link_only | Changed from ingest: the PDF is scanned images with no text layer (no OCR in v1), so it cannot be cited; kept as an official link | mac | 0 / 0 |
| SRC-STUDENT-AFFAIRS | iitb.ac.in/students/students-affair-office | 200 | Student affairs office | allowed | ingest | Student Affairs Office, tier 1 (one linked PDF returns 404) | mac | 2 / 11 |
| SRC-CONTACT | iitb.ac.in/contact-us | 200 | Contact us | allowed | ingest | Institute contact page, tier 1 | mac | 2 / 23 |
| SRC-GYMKHANA | gymkhana.iitb.ac.in/ | 200 | Students' Gymkhana | no robots.txt (404), nothing disallowed | ingest | Student body, tier 2 (never outranks tier 1) | mac | 1 / 8 |
| SRC-HOSTEL-FAQ | gymkhana.iitb.ac.in/~hostelaffairs/faq/ | 200 | Hostel FAQs & Guidelines | no robots.txt (404) | ingest | Hostel Affairs Council, tier 2 secondary guidance; answers come from the page's FAQ JSON-LD | mac | 1 / 28 |
| SRC-ASC | asc.iitb.ac.in/ | HEAD 200 | not fetched | no robots.txt (404) | link_only | Login portal; links only, no content fetched | mac (HEAD) | 0 / 0 |
| SRC-MOODLE | moodle.iitb.ac.in/ | HEAD 303 then 200 | not fetched | no robots.txt (404) | link_only | Login portal; data only through the Moodle API (read-only tools) | mac (HEAD) | 0 / 0 |
| SRC-SUPPORT | support.iitb.ac.in/ | HEAD 302 (curl); Python TLS handshake failed | not fetched | no robots.txt (404) | link_only | Support portal for hostel maintenance and IT tickets; link only | mac (HEAD) | 0 / 0 |
| SRC-INSTIAPP | insti.app/map | HEAD 200 | not fetched | allow all | link_only | Third-party student app (tier 2); link only | mac (HEAD) | 0 / 0 |

Totals: 9 ingest rows indexed (44 documents, 335 chunks; 6 extra PDFs failed extraction), 5 link_only, 0 blocked, 0 needs_review.
No row had a robots.txt rule excluding the fetched paths. No row was moved to blocked.
