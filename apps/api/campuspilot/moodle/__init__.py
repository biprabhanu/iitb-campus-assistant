"""Read-only IITB Moodle integration (REST, iCal fallback, demo fixtures)."""

import logging
import re

# httpx logs full request URLs at INFO, and an iCal URL contains a secret key (`authtoken`).
# httpcore's DEBUG lines can carry request details too. Keep both quiet.
# A level alone is not enough (anything that reconfigures logging can reset it), so a filter
# also strips the query (where `authtoken` lives) from every URL these loggers write.
_QUERY = re.compile(r"(https?://[^\s?#\"']+)[?#][^\s\"']*")


class _HideUrlQueries(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:
            return False  # can't check it, so don't write it
        if "?" in text or "#" in text:
            record.msg, record.args = _QUERY.sub(r"\1?<hidden>", text), ()
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
    logging.getLogger(_name).addFilter(_HideUrlQueries())
