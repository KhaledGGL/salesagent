from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ── Enums ────────────────────────────────────────────────────────────────────

class LeadSource(str, Enum):
    meta = "meta"
    google = "google"
    organic = "organic"

class LeadTemperature(str, Enum):
    cold = "cold"       # first touch
    warm = "warm"       # prior contact

class CallType(str, Enum):
    discovery = "discovery"
    treatment_plan = "treatment_plan"

class CallOutcome(str, Enum):
    sold = "sold"
    not_sold = "not_sold"
    no_show = "no_show"
    rescheduled = "rescheduled"

class CallStatus(str, Enum):
    received = "received"       # webhook received
    fetching = "fetching"       # fetching transcript from GHL
    queued = "queued"           # in Celery queue
    scoring = "scoring"         # Claude is scoring
    scored = "scored"           # done, scorecard written
    failed = "failed"           # something went wrong

class ObjectionType(str, Enum):
    price = "price"
    time = "time"
    spouse = "spouse"
    trust = "trust"
    urgency = "urgency"
    competitor = "competitor"
    fear = "fear"
    other = "other"

class HandlingQuality(str, Enum):
    poor = "poor"
    fair = "fair"
    good = "good"
    excellent = "excellent"

class CoachingCategory(str, Enum):
    rapport = "rapport"
    diagnosis = "diagnosis"
    objection_handling = "objection_handling"
    close = "close"
    compliance = "compliance"

class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

class KpiPeriod(str, Enum):
    day_30 = "30d"
    day_60 = "60d"
    day_90 = "90d"
    weekly = "weekly"


# ── GHL Webhook Payload ───────────────────────────────────────────────────────

class GHLWebhookPayload(BaseModel):
    """Normalized fields we extract from the GHL call-completed webhook."""
    message_id: str
    conversation_id: str
    contact_id: str
    location_id: str
    user_id: str                        # rep's GHL user ID
    duration_seconds: Optional[int] = None
    called_at: Optional[str] = None     # ISO timestamp


class GHLTranscriptReadyPayload(BaseModel):
    """Inline-transcript webhook from GHL's "Transcript Generated" trigger.

    Unlike GHLWebhookPayload (which carries only metadata and forces a
    follow-up GHL API call to fetch the transcript), this payload delivers
    the transcript text directly. This eliminates one API round-trip and
    sidesteps the race where "call ended" fires before transcription is done.

    Field names mirror GHL's `transcript_generated.*` merge tag namespace
    so the webhook body in the GHL workflow editor maps 1:1.
    """
    call_sid: str                       # used as ghl_message_id (Twilio call SID, globally unique)
    call_user_id: str                   # rep's GHL user ID
    call_user_name: Optional[str] = None  # rep's display name (e.g. "John Smith")
    call_transcript: str                # the actual dialogue text
    call_duration: Optional[int] = None
    call_status: Optional[str] = None   # we filter to "completed" only
    call_from: Optional[str] = None     # phone number, not stored
    call_to: Optional[str] = None       # phone number, not stored
    contact_id: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


# ── Scorecard (Claude output) ─────────────────────────────────────────────────

class ScoreBand(BaseModel):
    rapport: int = Field(ge=1, le=10)
    diagnosis: int = Field(ge=1, le=10)
    objection_handling: int = Field(ge=1, le=10)
    close: int = Field(ge=1, le=10)
    compliance: int = Field(ge=1, le=10)
    overall: int = Field(ge=1, le=10)

class WinLossMoment(BaseModel):
    timestamp_seconds: int
    description: str

class CoachingMoment(BaseModel):
    timestamp_seconds: int
    category: CoachingCategory
    severity: Severity
    note: str

class Objection(BaseModel):
    timestamp_seconds: int
    objection_type: ObjectionType
    objection_text: str
    handling_quality: HandlingQuality

class ScorecardOutput(BaseModel):
    """Exact shape Claude must return."""
    scores: ScoreBand
    therapist_mode_flag: bool
    therapist_mode_reason: Optional[str] = None
    ai_summary: str
    win_loss_moment: WinLossMoment
    coaching_moments: list[CoachingMoment]
    objections: list[Objection]


# ── Coaching Lesson (Claude output) ──────────────────────────────────────────

class CoachingExample(BaseModel):
    rep_name: str
    what_they_did: str
    quote: str

class CategoryInsight(BaseModel):
    category: str
    best_examples: list[CoachingExample] = []
    worst_examples: list[CoachingExample] = []
    advice: str

class CoachingLessonOutput(BaseModel):
    """Shape Claude must return for weekly coaching lesson."""
    headline: str
    category_insights: list[CategoryInsight]
    weekly_focus: str


# ── Marketing Intelligence (Claude output) ───────────────────────────────────

class MessagingAngle(BaseModel):
    pain_point: str
    frequency: int
    example_quotes: list[str]

class SourceAnalysis(BaseModel):
    source: str
    close_rate: Optional[float] = None
    quality_assessment: str
    recommendation: str

class PrequalRec(BaseModel):
    recommendation: str
    rationale: str

class PositioningGap(BaseModel):
    gap: str
    evidence: str
    recommendation: str

class MarketingIntelOutput(BaseModel):
    """Shape Claude must return for weekly marketing intelligence."""
    headline: str
    messaging_angles: list[MessagingAngle]
    source_analysis: list[SourceAnalysis]
    prequalification_recs: list[PrequalRec]
    positioning_gaps: list[PositioningGap]
