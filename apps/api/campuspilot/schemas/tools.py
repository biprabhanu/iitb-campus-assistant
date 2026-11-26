"""Tool input/output models (docs/CONTRACT.md §4).

The model may only *request* these tools. The backend validates every argument
with the `*Input` model (extra fields are rejected) before running anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MoodleMode = Literal["rest", "ical", "demo"]


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- search_campus_docs ----------


class SearchCampusDocsInput(_StrictInput):
    query: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=50)
    audience: str | None = Field(default=None, max_length=50)
    k: int = Field(default=6, ge=1, le=8)


class DocChunkHit(BaseModel):
    chunk_id: int
    source_id: str
    document_id: int
    title: str  # document title (falls back to source title)
    issuer: str
    url: str  # the document URL (PDF or page), always from the registry/crawl, never the model
    heading_path: str = ""
    page: int | None = None
    text: str
    audience: str | None = None
    authority_tier: int
    category: str | None = None
    checked_at: str | None = None  # document fetched_at (ISO)
    published_at: str | None = None  # date found in document text, else None
    score: float  # higher is better (negated BM25 plus tier boost)


class SearchCampusDocsOutput(BaseModel):
    hits: list[DocChunkHit] = Field(default_factory=list)


# ---------- get_official_link ----------


class GetOfficialLinkInput(_StrictInput):
    topic: str = Field(min_length=1, max_length=200)


class OfficialLink(BaseModel):
    source_id: str
    title: str
    issuer: str
    url: str
    category: str
    notes: str = ""


class GetOfficialLinkOutput(BaseModel):
    links: list[OfficialLink] = Field(default_factory=list)


# ---------- Moodle tools ----------


class ListMyCoursesInput(_StrictInput):
    pass


class Course(BaseModel):
    id: int
    short_name: str
    full_name: str
    url: str


class ListMyCoursesOutput(BaseModel):
    courses: list[Course] = Field(default_factory=list)
    mode: MoodleMode
    demo: bool = False
    note: str = ""  # e.g. "Courses are not available in iCal mode."


class GetMyDeadlinesInput(_StrictInput):
    days_ahead: int = Field(default=7, ge=1, le=60)
    course_code: str | None = Field(default=None, max_length=50)


class Deadline(BaseModel):
    id: str  # stable id from Moodle, e.g. "assign-123" or "event-456"
    title: str
    course: str  # course short name, e.g. "IE624"
    due_at: datetime  # timezone-aware
    activity_url: str | None = None
    kind: Literal["assignment", "event"]


class GetMyDeadlinesOutput(BaseModel):
    deadlines: list[Deadline] = Field(default_factory=list)  # sorted by due_at
    mode: MoodleMode
    demo: bool = False
    note: str = ""


class GetCourseContentsInput(_StrictInput):
    course_code: str = Field(min_length=1, max_length=50)


class CourseResource(BaseModel):
    name: str
    type: str  # Moodle modname: resource, url, assign, forum, page, folder...
    url: str | None = None


class CourseSection(BaseModel):
    name: str
    resources: list[CourseResource] = Field(default_factory=list)


class GetCourseContentsOutput(BaseModel):
    course: Course | None = None
    sections: list[CourseSection] = Field(default_factory=list)
    mode: MoodleMode
    demo: bool = False
    note: str = ""
