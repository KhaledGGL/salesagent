from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum


# ── Enums ────────────────────────────────────────────────────────────────────

class LeadSource(str, Enum):
    meta = "meta"
    google = "google"
    organic = "organic"

class LeadTemperature(str, Enum):
    cold = "cold"       # first touch
    warm = "warm"       # prior contact

class CallOutcome(str, Enum):
    sold = "sold"
    not_sold = "not_sold"
    follow_up = "follow_up"
    no_show = "no_show"
    rescheduled = "rescheduled"

class CallStatus(str, Enum):
    received = "received"       # webhook received, transcript stored, awaiting scoring
    scoring = "scoring"         # Claude is scoring
    scored = "scored"           # done, scorecard written
    failed = "failed"           # something went wrong
    # 'fetching' and 'queued' are legacy enum values from when transcripts
    # were fetched via the GHL Conversations API. Kept in the enum for
    # backwards compatibility with any in-flight rows; new rows never use them.

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

class WeeklyReportType(str, Enum):
    sales = "sales"
    coaching = "coaching"
    marketing = "marketing"


# ── Webhook payload ──────────────────────────────────────────────────────────

class GHLTranscriptReadyPayload(BaseModel):
    """Inline-transcript webhook payload (the only ingestion model).

    The GHL workflow's "Transcript Generated" trigger POSTs a body shaped
    like this to /webhooks/ghl/transcript-ready. Field names mirror GHL's
    merge-tag namespace so the workflow editor maps 1:1.

    All attribution comes from UTM merge tags in this payload — no
    follow-up GHL Contacts API call is made. This means clients onboard
    without issuing a GHL token and source attribution is per-campaign,
    per-creative, per-keyword instead of just three buckets.
    """
    # ── Call identity ──────────────────────────────────────────────────
    call_sid: str                       # used as ghl_message_id (globally unique)
    call_user_id: str                   # rep's GHL user ID
    call_user_name: Optional[str] = None  # rep's display name (e.g. "John Smith")
    call_transcript: str                # the actual dialogue text
    call_duration: Optional[int] = None
    call_status: Optional[str] = None   # we filter to "completed" only
    call_from: Optional[str] = None     # phone number, not stored
    call_to: Optional[str] = None       # phone number, not stored

    # ── Contact ────────────────────────────────────────────────────────
    contact_id: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    # ── UTM attribution (replaces GHL Contacts API enrichment) ────────
    # All optional — leads with no UTMs (e.g. direct/organic) just leave
    # them null. utm_source feeds the lead_source enum (with normalization),
    # the rest land on dedicated columns for campaign/creative-level analysis.
    utm_source:   Optional[str] = None
    utm_medium:   Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content:  Optional[str] = None
    utm_term:     Optional[str] = None


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
    outcome: Literal["sold", "not_sold", "follow_up"]
    outcome_confidence: float = Field(ge=0.0, le=1.0)
    outcome_evidence: str
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
