"""A small, focused check: does this question need ONE clarifying question first?

Why a separate call: with tools offered, Gemma's choice between "ask" and "search" for a
question like "Can I change my room?" flipped run to run (even at temperature 0, likely
because of Ollama's prompt cache). A call whose only job is this yes/no decision, answered
as JSON, is far more stable. It costs one short extra call (~0.5 s).
"""

from __future__ import annotations

import json
import logging
import re

from campuspilot.llm.base import LLMClient, Message
from campuspilot.schemas.chat import ChatTurn, FollowUp

log = logging.getLogger("campuspilot.clarify")

CLARIFY_PROMPT = """You check questions sent to CampusPilot, an assistant for IIT Bombay \
students. Decide if the question needs ONE clarifying question before it can be answered \
correctly.

It needs one only when the correct answer differs by the student's programme (UG / PG / PhD), \
hostel, semester, year of entry or category, AND the student has not said which.
Needs clarification: "Can I change my room?", "When do I pay my fees?", "How many credits do \
I need to graduate?", "Can I get a hostel?", "What is my exam schedule?".
Does NOT need clarification: "Where can I find the academic calendar?", "How do I report a \
hostel maintenance issue?", "What's due this week?", "Code of conduct basics", "What is the \
mess menu on 3 March 2031?", "How do I contact the Dean of Student Affairs?", greetings, and \
any question where the earlier conversation already says the programme or hostel.

Reply with JSON only, no other text:
{"clarify": true or false, "question": "<one short question, or empty>", \
"options": ["<2 to 4 short options>"]}"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse(content: str) -> FollowUp | None:
    match = _JSON_RE.search(content or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("clarify") is not True:
        return None
    question = str(data.get("question") or "").strip()[:300]
    options = [str(o).strip()[:60] for o in data.get("options") or [] if str(o).strip()][:4]
    if not question:
        return None
    return FollowUp(question=question, options=options)


async def needs_clarification(
    llm: LLMClient, message: str, history: list[ChatTurn]
) -> FollowUp | None:
    """Return a clarifying question, or None to carry on normally. Never raises for bad
    model output (that just means "no clarification"); model/transport errors propagate."""
    recent = "\n".join(f"{t.role}: {t.content[:300]}" for t in history[-4:])
    user_text = f"Earlier conversation:\n{recent}\n\n" if recent else ""
    user_text += f"Question: {message}"
    messages: list[Message] = [
        {"role": "system", "content": CLARIFY_PROMPT},
        {"role": "user", "content": user_text},
    ]
    reply = await llm.chat(messages, None)
    follow_up = _parse(reply.content)
    log.debug("clarify precheck: %s", "ask" if follow_up else "no")
    return follow_up
