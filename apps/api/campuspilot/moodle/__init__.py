"""Read-only IITB Moodle integration (REST, iCal fallback, demo fixtures)."""

import logging

# httpx logs full request URLs at INFO, and an iCal URL contains a secret key.
logging.getLogger("httpx").setLevel(logging.WARNING)
