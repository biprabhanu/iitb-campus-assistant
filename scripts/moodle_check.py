"""Live, read-only Moodle check. Prints only safe facts (counts), never secrets or content.

Local:   .venv/bin/python ../../scripts/moodle_check.py        (run from apps/api)
Hosted:  .venv/bin/python ../../scripts/moodle_check.py --api-url https://your-api.example
         (sends MOODLE_ICAL_URL, or MOODLE_TOKEN, from the repo .env to /v1/moodle/check)
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

SETUP_HELP = """Moodle is not configured. To connect it (read-only):
  Moodle -> Calendar -> Export calendar -> All events, Recent and next 60 days ->
  Get calendar URL. Paste it in the app Settings (stored in the Keychain), or put
  MOODLE_ICAL_URL=... in the untracked .env at the repo root. The link contains a private
  authtoken: treat it like a password.
Never share your IITB password; this app never asks for it."""

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def read_env_value(name: str, path: Path = ENV_PATH) -> str:
    """Read one KEY=value from a .env file (simple parser; no shell expansion)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("'\"")
    return ""


def check_remote(api_url: str) -> int:
    import httpx

    token = read_env_value("MOODLE_TOKEN")
    ical = read_env_value("MOODLE_ICAL_URL")
    if token:
        headers = {"X-Moodle-Token": token}
    elif ical:
        headers = {"X-Moodle-Ical-Url": ical}
    else:
        print(SETUP_HELP)
        return 0
    url = api_url.rstrip("/") + "/v1/moodle/check"
    try:
        response = httpx.post(url, headers=headers, timeout=30.0, follow_redirects=False)
    except httpx.HTTPError:
        print("Could not reach the API.")
        return 1
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if response.status_code == 200 and body.get("ok"):
        print(f"ok: True  mode: {body.get('mode')}  site: {body.get('site_name') or '-'}")
        return 0
    detail = body.get("detail")
    code = body.get("code") or (detail.get("code") if isinstance(detail, dict) else None)
    print(f"ok: False  HTTP {response.status_code}  error: {code or 'unknown'}")
    return 1


async def check_local() -> int:
    from campuspilot.moodle.client import MoodleClient
    from campuspilot.moodle.tools import (
        MoodleError,
        get_my_deadlines,
        list_my_courses,
        moodle_status,
        resolve_source,
    )
    from campuspilot.schemas.tools import GetMyDeadlinesInput, ListMyCoursesInput

    status, mode = await moodle_status()
    if status == "not_configured" and mode == "none":
        print(SETUP_HELP)
        return 0
    print(f"mode: {mode}  status: {status}")
    if mode == "demo":
        print("(demo fixtures; nothing real is connected)")
    try:
        source = resolve_source()
        if source.mode == "rest":
            print(f"site: {(await MoodleClient(source.secret).site_info()).get('sitename', '?')}")
        courses = await list_my_courses(ListMyCoursesInput())
        deadlines = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=14))
    except MoodleError as err:
        print(f"Moodle error [{err.code}]: {err.message}")
        return 1
    print(f"courses: {len(courses.courses)}" + (f"  ({courses.note})" if courses.note else ""))
    print(f"deadlines in next 14 days: {len(deadlines.deadlines)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", help="check through a deployed API instead of locally")
    args = parser.parse_args()
    if args.api_url:
        return check_remote(args.api_url)
    return asyncio.run(check_local())


if __name__ == "__main__":
    raise SystemExit(main())
