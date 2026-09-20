"""Structured contracts exchanged between EcoSentinel agents and the API.

Each specialist agent emits a typed result. The Coordinator consumes only these
results (never raw provider data), which keeps agents independent and swappable.
JSON is camelCase so it maps 1:1 onto frontend/src/types/agents.ts.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

RiskLevel = Literal["LOW", "MODERATE", "HIGH"]
SpecialistAgentId = Literal["air", "water", "waste"]
AgentId = Literal["air", "water", "waste", "coordinator"]
MeasurementStatus = Literal["normal", "elevated", "critical", "missing"]
WasteCategory = Literal["plastic", "paper", "other"]
DataFreshness = Literal["live", "delayed", "demo"]
WaterSourceType = Literal["live_iot", "monitoring_station", "historical", "demo"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------- location


class GeoPoint(ApiModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class LocationContext(ApiModel):
    """The single, normalized location every agent receives."""

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    display_name: Optional[str] = Field(default=None, max_length=300)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=120)
    postcode: Optional[str] = Field(default=None, max_length=40)
    neighbourhood: Optional[str] = Field(default=None, max_length=120)
    water_feature: Optional[str] = Field(default=None, max_length=160)
    source: Literal["browser_geolocation", "preset"] = "browser_geolocation"
    geocoding: Literal["nominatim", "cached", "unresolved", "preset"] = "unresolved"
    preset_id: Optional[str] = Field(default=None, max_length=40)
    timestamp: Optional[datetime] = None


class PlaceSearchRequest(ApiModel):
    """Free-text place search (Nominatim forward geocoding)."""

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)
    #: ISO 3166-1 alpha-2 codes, comma separated, restricting the search. Defaults to India:
    #: this is an India-only safety application, and an unrestricted search returns Whitefield,
    #: New Hampshire above Whitefield, Bengaluru. Pass "" to search worldwide.
    country_codes: Optional[str] = Field(default="in", max_length=64)


class PlaceMatch(ApiModel):
    display_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    category: Optional[str] = None
    place_type: Optional[str] = None
    importance: Optional[float] = None
    #: True when the match is itself a water feature — a lake, river, reservoir and so on.
    is_water: bool = False
    #: ISO 3166-1 alpha-2 from Nominatim's structured address. None when unverified.
    country_code: Optional[str] = None


class PlaceSearchResponse(ApiModel):
    query: str
    #: Which countries the search was restricted to, echoed so a caller can see the scope applied.
    country_codes: Optional[str] = None
    matches: List[PlaceMatch] = Field(default_factory=list)
    cached: bool = False


class NearbyWaterRequest(ApiModel):
    """Water bodies near a point, from OpenStreetMap via Overpass."""

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_m: Optional[int] = Field(default=None, ge=50, le=5000)
    limit: Optional[int] = Field(default=None, ge=1, le=50)


class NearbyWaterBody(ApiModel):
    """One OSM water feature. Geography only — it says nothing about water quality."""

    osm_id: str
    name: Optional[str] = None
    #: Raw OSM tag value, e.g. "lake", "drain".
    kind: str
    #: Human label for `kind`, e.g. "Lake", "Storm drain".
    label: str
    #: True for waterways that flow (river, stream, canal, drain) rather than standing water.
    flowing: bool = False
    latitude: float
    longitude: float
    distance_km: float


class NearbyWaterResponse(ApiModel):
    """Always answers. `status` says why the list is empty rather than pretending there is no water."""

    status: Literal["ok", "disabled", "unavailable"] = "ok"
    message: Optional[str] = None
    bodies: List[NearbyWaterBody] = Field(default_factory=list)
    #: Closest named body, promoted for convenience — this is what a report should cite.
    nearest_named: Optional[NearbyWaterBody] = None
    radius_m: Optional[int] = None
    cached: bool = False


class GeographicContextRequest(ApiModel):
    """Contextual OSM features near a point (Overpass)."""

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_m: Optional[int] = Field(default=None, ge=50, le=5000)
    per_category: Optional[int] = Field(default=None, ge=1, le=50)


class GeographicFeature(ApiModel):
    """One mapped OpenStreetMap feature near the analysis location.

    CONTEXT ONLY. A mapped feature is something a contributor drew and tagged — never a
    measurement, an emission, or evidence that anything is polluting. See the module docstring
    in services/overpass_service.py for the wording rules this data must be described with.
    """

    osm_id: str
    name: Optional[str] = None
    #: industrial | waste | waterway | road
    category: Literal["industrial", "waste", "waterway", "road"]
    #: Raw OSM tag value, e.g. "landfill".
    kind: str
    #: Human label for `kind`, e.g. "Landfill".
    label: str
    latitude: float
    longitude: float
    distance_km: float


class GeographicContext(ApiModel):
    """Optional geographic enrichment for one analysis.

    `available` is False whenever Overpass was off, unreachable, rate-limited or returned
    nothing usable. It NEVER contributes to a risk score and never reaches the Coordinator —
    it only tells a reader what is mapped around the point they analysed.
    """

    available: bool = False
    source: str = "OpenStreetMap/Overpass"
    status: Literal["ok", "disabled", "unavailable", "skipped"] = "skipped"
    message: Optional[str] = None
    industrial_features: List[GeographicFeature] = Field(default_factory=list)
    waste_facilities: List[GeographicFeature] = Field(default_factory=list)
    waterways: List[GeographicFeature] = Field(default_factory=list)
    roads: List[GeographicFeature] = Field(default_factory=list)
    radius_m: Optional[int] = None
    cached: bool = False

    @property
    def total_features(self) -> int:
        return len(self.industrial_features) + len(self.waste_facilities) + len(self.waterways) + len(self.roads)


class ReverseGeocodeRequest(ApiModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class GeocodeResult(ApiModel):
    display_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    #: ISO 3166-1 alpha-2, lowercased — what a country check is written against.
    country_code: Optional[str] = None
    postcode: Optional[str] = None
    neighbourhood: Optional[str] = None
    water_feature: Optional[str] = None
    cached: bool = False


# ---------------------------------------------------------------- agent outputs


class Measurement(ApiModel):
    key: str
    label: str
    value: Optional[float]
    unit: str
    threshold: Optional[float] = None
    threshold_label: Optional[str] = None
    sub_score: Optional[float] = None
    status: MeasurementStatus = "normal"
    averaging_period: Optional[str] = None
    who_reference: Optional[float] = None
    who_averaging_period: Optional[str] = None
    cpcb_standard: Optional[float] = None
    cpcb_averaging_period: Optional[str] = None
    ratio_to_reference: Optional[float] = None
    difference_to_reference: Optional[float] = None
    percentage_difference: Optional[float] = None
    interpretation_label: Optional[str] = None
    comparison_status: Optional[str] = None
    comparison_note: Optional[str] = None
    health_effects: Optional[List[str]] = None
    major_sources: Optional[List[Dict[str, Any]]] = None
    is_secondary_pollutant: Optional[bool] = None
    precursor_pollutants: Optional[List[str]] = None


class Finding(ApiModel):
    code: str
    label: str
    detail: str
    impact: float = Field(ge=0, le=1)


class AgentResultBase(ApiModel):
    location: str
    risk_level: RiskLevel
    risk_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    timestamp: datetime
    data_source: str
    is_mock: bool
    measurements: List[Measurement]
    findings: List[Finding]
    warnings: List[str] = Field(default_factory=list)


class AirAgentResult(AgentResultBase):
    agent: Literal["air"] = "air"
    station_id: str
    station_name: str
    pm25: Optional[float]
    pm10: Optional[float]
    no2: Optional[float]
    o3: Optional[float]
    aqi: Optional[int]
    aqi_category: Optional[str]
    dominant_pollutant: Optional[str]
    anomalies: List[str] = Field(default_factory=list)
    station_distance_km: Optional[float] = None
    reference_grade: Optional[bool] = None
    source_url: Optional[str] = None
    pollutant_sources: Dict[str, str] = Field(default_factory=dict)
    source_location: Optional[GeoPoint] = None
    data_age_minutes: Optional[int] = None
    freshness: Optional[DataFreshness] = None


class VisionDetectionBox(ApiModel):
    """Pixel-space box as returned by the detector, in the uploaded image's own coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float


class VisionDetection(ApiModel):
    """One detected object. `class_name` is whatever the trained model reports — never remapped.

    `semantic_category` is this project's INTERPRETATION of that raw class, kept in its own field
    so the two can never be confused. The detector says `bottle`; the interpretation says that a
    bottle floating in water is `visible_surface_litter`. A COCO `person` or `kite` is a real
    detection and stays in `detections`, but it is `non_pollution_object` and must not be counted
    as visible pollution (see core/investigation.is_pollution_class, the single taxonomy).

    Values:
      visible_surface_litter  the class indicates anthropogenic litter/debris
      non_pollution_object    the detector's own class rules pollution out (person, boat, car…)
      unclassified_object     a real detection this taxonomy makes no claim about
    """

    class_name: str
    confidence: float = Field(ge=0, le=1)
    bbox: VisionDetectionBox
    semantic_category: Literal[
        "visible_surface_litter", "non_pollution_object", "unclassified_object"
    ] = "unclassified_object"


class WaterVisionReport(ApiModel):
    """Visual water-pollution detection (YOLO26).

    This is a VISUAL signal only: it counts pollution objects visible in an image. It does not
    and cannot measure pH, turbidity, dissolved oxygen, temperature or chemical contamination —
    those come from the sensor/dataset readings carried in `measurements` on WaterAgentResult.
    """

    available: bool = False
    # not_run: no image supplied | model_not_configured | unavailable: dependency/model/inference failure
    status: Literal["ok", "not_run", "model_not_configured", "unavailable"] = "not_run"
    model: Optional[str] = None
    message: Optional[str] = None
    detections: List[VisionDetection] = Field(default_factory=list)
    object_counts: Dict[str, int] = Field(default_factory=dict)
    #: EVERY object the detector found, pollution or not. Kept complete and unfiltered: hiding a
    #: detection would misrepresent what the model actually did.
    total_objects: int = 0
    #: The subset carrying `semantic_category == "visible_surface_litter"`. THIS is the number that
    #: means "visible pollution", and the only one that may move a risk score. The two are separate
    #: fields because a COCO detector in a river scene reports people, boats and birds, and
    #: counting those as litter invents pollution that nobody observed.
    pollution_objects: int = 0
    #: Detections whose own class rules pollution out — reported so the frame is fully accounted for.
    non_pollution_objects: int = 0
    #: Counts restricted to the pollution subset, for display under a "visible litter" heading.
    pollution_counts: Dict[str, int] = Field(default_factory=dict)
    confidence_threshold: Optional[float] = None
    # Normalised 0..1 density score and its band. Only set when status == "ok".
    # Computed from `pollution_objects`, never from `total_objects`.
    visual_score: Optional[float] = Field(default=None, ge=0, le=1)
    visual_level: Optional[RiskLevel] = None
    annotated_image: Optional[str] = None  # data URI, only when the detector can render one
    #: Frame size in pixels. A bbox is meaningless without the frame it was measured against, so
    #: without these no honest statement can be made about WHERE in the image an object sits.
    image_width: Optional[int] = None
    image_height: Optional[int] = None


class DatasetNeighbour(ApiModel):
    """One reference frame the uploaded photo was compared against."""

    file: str
    class_name: str
    label: str
    similarity: float = Field(ge=0, le=1)


class WaterDatasetMatch(ApiModel):
    """Appearance match against the labelled reference dataset.

    This compares COLOUR DISTRIBUTION against labelled reference frames. A confident match to a
    contaminated class is visual corroboration that an area looks contaminated; it is not a
    measurement of pH, turbidity or any chemical parameter, and never sets one.
    """

    # not_run: no image | indexing: reference index still building | index_missing: no dataset
    # no_match: nothing cleared the similarity threshold | unavailable: dependency/decode failure
    status: Literal["ok", "no_match", "not_run", "indexing", "index_missing", "unavailable"] = "not_run"
    message: Optional[str] = None
    #: True only when a matched class maps to a level this deployment treats as contaminated.
    contaminated: bool = False
    matched_class: Optional[str] = None
    matched_label: Optional[str] = None
    contamination_level: Optional[RiskLevel] = None
    #: Similarity of the single closest reference frame (histogram intersection, 0..1).
    similarity: Optional[float] = Field(default=None, ge=0, le=1)
    #: Share of the k-nearest-neighbour vote won by the matched class.
    vote_share: Optional[float] = Field(default=None, ge=0, le=1)
    #: True when the photo is essentially a frame the dataset already contains (replayed sample).
    near_duplicate: bool = False
    duplicate_of: Optional[str] = None
    neighbours: List[DatasetNeighbour] = Field(default_factory=list)
    dataset_size: Optional[int] = None
    match_threshold: Optional[float] = None
    indexed_at: Optional[datetime] = None
    #: 0..1 build progress, only while status == "indexing".
    progress: Optional[float] = Field(default=None, ge=0, le=1)
    #: Measured reliability of this matcher, carried with every result so no consumer can read
    #: the flag as a verdict. See services/water_dataset_match_service.py for the numbers.
    caveat: Optional[str] = None


class WaterAgentResult(AgentResultBase):
    agent: Literal["water"] = "water"
    sensor_id: str
    sensor_name: str
    sensor_status: Literal["online", "degraded", "offline"]
    ph: Optional[float]
    turbidity: Optional[float]
    temperature: Optional[float]
    tds: Optional[float] = None
    source_type: WaterSourceType = "demo"
    source_name: Optional[str] = None
    sensor_distance_km: Optional[float] = None
    source_location: Optional[GeoPoint] = None
    data_age_minutes: Optional[int] = None
    # Optional visual-pollution signal. Absent/`not_run` for every existing caller that does not
    # upload an image, so the Coordinator contract is unchanged.
    visual_pollution: Optional[WaterVisionReport] = None
    # Water-quality-only score, kept alongside risk_score whenever vision shifted the combined
    # figure, so the blend stays auditable.
    water_quality_score: Optional[float] = Field(default=None, ge=0, le=1)
    # Optional appearance match against the labelled reference dataset. Absent/`not_run` for
    # every caller that does not upload an image.
    dataset_match: Optional[WaterDatasetMatch] = None
    # Clicked-frame explainable-AI report (WHERE / WHY / WHAT NEXT). Present only when a frame was
    # submitted for investigation; absent for every existing caller.
    investigation: Optional["FrameInvestigation"] = None


class Detection(ApiModel):
    id: str
    label: str
    category: WasteCategory
    confidence: float
    bbox: List[float]  # x, y, width, height — normalised to 0..1


class WasteCounts(ApiModel):
    plastic: int
    paper: int
    other: int


class WasteAgentResult(AgentResultBase):
    agent: Literal["waste"] = "waste"
    source_id: str
    source_name: str
    input_type: Literal["camera", "upload"]
    model: str
    total_objects: int
    counts: WasteCounts
    density_index: float
    detections: List[Detection]
    source_distance_km: Optional[float] = None
    source_location: Optional[GeoPoint] = None


# ---------------------------------------------------------------- coordinator


class SignalContribution(ApiModel):
    agent: SpecialistAgentId
    risk_level: RiskLevel
    risk_score: float
    weight: float
    contribution: float


class ContributingFactor(ApiModel):
    agent: SpecialistAgentId
    label: str
    detail: str


class Recommendation(ApiModel):
    id: str
    priority: int
    title: str
    explanation: str
    agent: Literal["air", "water", "waste", "all"]
    urgency: Literal["Immediate", "Within 24h", "Routine"]
    action_label: str


class CoordinatorResult(ApiModel):
    agent: Literal["coordinator"] = "coordinator"
    location: str
    overall_risk_level: RiskLevel
    overall_score: float
    confidence: float
    reasoning: str
    cross_signal_insights: List[str]
    contributing_factors: List[ContributingFactor]
    contributions: List[SignalContribution]
    cross_signal_adjustment: float
    dominant_agents: List[SpecialistAgentId]
    inputs_received: List[SpecialistAgentId]
    missing_inputs: List[SpecialistAgentId]
    recommendations: List[Recommendation]
    timestamp: datetime
    # Deterministic, always populated: freshness/mock/missing-agent caveats derived only from the
    # specialist reports themselves (see CoordinatorAgent._data_limitations). Never LLM-generated.
    data_limitations: List[str] = Field(default_factory=list)
    # True only when insufficient_data is set OR every specialist agent failed/timed out.
    insufficient_data: bool = False
    # Optional natural-language narrative from the Coordinator LLM (agents/llm_reasoning.py). None
    # unless LLM_PROVIDER is configured and the call succeeds — the deterministic `reasoning` and
    # `cross_signal_insights` fields above are always present and are never replaced by the LLM.
    llm_narrative: Optional[str] = None
    llm_enhanced: bool = False


# ---------------------------------------------------------------- decision engine
#
# The LangGraph decision layer turns specialist reports into normalized EVIDENCE, then into
# detected PROBLEMS, then into one DECISION. Every field below is computed deterministically
# (core/evidence.py, core/decision.py). The optional LLM writes `llm_explanation` and nothing
# else — it never sets a score, a priority, a confidence, or an item of evidence.

EvidenceDomain = Literal["air", "water", "waste", "geographic"]
EvidenceKind = Literal["measurement", "detection", "context", "derived"]
#: Direction is only ever set from a real baseline comparison. With no history for a signal it
#: stays "unknown" — an unmeasured trend is never reported as "stable".
EvidenceDirection = Literal["improving", "deteriorating", "stable", "unknown"]
ProblemCategory = Literal["air", "water", "waste", "cross_signal", "unknown"]
#: observed            = the measurement itself is the problem (a threshold exceedance)
#: supported_hypothesis = several independent signals point the same way; cause NOT established
#: unconfirmed         = suggested by context alone, awaiting measurement
CausalStatus = Literal["observed", "supported_hypothesis", "unconfirmed"]
OverallDirection = Literal["improving", "deteriorating", "mixed", "stable", "insufficient_history"]


class EnvironmentalEvidence(ApiModel):
    """One normalized observation, whatever domain produced it.

    Evidence is a fact plus its provenance — never a conclusion. `severity` is derived from the
    specialist's own `sub_score`/`impact`, so it stays on the existing deterministic scale.
    """

    evidence_id: str
    domain: EvidenceDomain
    kind: EvidenceKind
    label: str
    detail: str
    value: Optional[float] = None
    unit: Optional[str] = None
    threshold: Optional[float] = None
    status: MeasurementStatus = "normal"
    severity: float = Field(default=0.0, ge=0, le=1)
    confidence: float = Field(default=0.0, ge=0, le=1)
    direction: EvidenceDirection = "unknown"
    source: str = ""
    observed_at: Optional[datetime] = None
    is_mock: bool = False


class EnvironmentalProblem(ApiModel):
    """A problem the evidence supports. Never created without at least one evidence id."""

    problem_id: str
    category: ProblemCategory
    title: str
    description: str
    severity: RiskLevel
    severity_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    #: Deterministic ranking score — see core/decision.py::problem_priority for the exact formula.
    priority: float = Field(default=0.0, ge=0, le=1)
    evidence_ids: List[str] = Field(default_factory=list)
    causal_status: CausalStatus = "observed"
    affected_area: Optional[str] = None


class CrossSignalFinding(ApiModel):
    """Independent signals co-occurring. Never a causal claim — `causality` is fixed."""

    finding_id: str
    title: str
    detail: str
    domains: List[EvidenceDomain] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    causality: Literal["not_established"] = "not_established"


class EvidenceConflict(ApiModel):
    """Evidence pointing in opposite directions — surfaced, never averaged away."""

    conflict_id: str
    detail: str
    evidence_ids: List[str] = Field(default_factory=list)


class InvestigationAction(ApiModel):
    """What to collect next, why it matters, and who can supply it."""

    action_id: str
    title: str
    missing_data: str
    rationale: str
    provider: str
    priority: int = 1


class DecisionTraceStep(ApiModel):
    """One step of the explainability chain: decision -> problem -> evidence -> measurement."""

    step: int
    stage: str
    detail: str
    evidence_ids: List[str] = Field(default_factory=list)


class TriageDecision(ApiModel):
    """Which investigations the graph chose to run, and why.

    Domains are selected by deterministic availability rules only. An LLM never decides that a
    domain is irrelevant — skipping a measurement because a model guessed would hide real risk.
    """

    domains: List[EvidenceDomain] = Field(default_factory=list)
    skipped: List[EvidenceDomain] = Field(default_factory=list)
    rationale: List[str] = Field(default_factory=list)


class RetrievedKnowledge(ApiModel):
    """One passage retrieved from the knowledge corpus, with everything needed to cite it.

    CONTEXT, NOT EVIDENCE. Retrieved knowledge explains what a measurement means; it is not a
    measurement. It never enters the evidence list, carries no severity, and cannot move a risk
    score — the same rule geographic context follows.

    `chunk_id` is `<document_id>#<section-slug>` and resolves to an exact section of an exact file
    in `backend/knowledge/`. `source_file` names the repository file that knowledge was taken
    from, so a reader can open the original. A citation nobody can check is worse than none.
    """

    chunk_id: str
    document_id: str
    document_title: str
    section: str
    domain: str
    #: Repository file the knowledge came from. None means the citation cannot be resolved.
    source_file: Optional[str] = None
    #: The retrieved passage itself.
    content: str
    #: Cosine similarity, reported rather than hidden so a weak match is visibly weak.
    score: float = Field(default=0.0, ge=0, le=1)
    #: True when the chunk's domain matched the query's, so a ranking can be explained.
    domain_matched: bool = False
    #: Which part of the pipeline the passage was retrieved for, e.g. "Water Agent".
    used_by: Optional[str] = None


class KnowledgeRetrieval(ApiModel):
    """The retrieval step as a whole: the query asked, and what came back.

    The query is shown because it is built deterministically from the evidence — not written by a
    language model — and showing it is what lets a reader check that the system searched for what
    it actually found.
    """

    #: not_run: retrieval was not attempted | ok | unavailable: the corpus could not be loaded
    status: Literal["ok", "not_run", "unavailable"] = "not_run"
    query: str = ""
    results: List[RetrievedKnowledge] = Field(default_factory=list)
    #: Retrieval technique, stated plainly rather than implying a semantic model is running.
    embedding: str = "tfidf-sparse-lexical"
    documents_indexed: int = 0
    chunks_indexed: int = 0
    #: Cosine floor below which a chunk is not returned at all.
    min_score: Optional[float] = None
    message: Optional[str] = None


class EnvironmentalDecision(ApiModel):
    """The engine's output: what the evidence points to, how sure, and what to do next."""

    primary_problem: Optional[EnvironmentalProblem] = None
    secondary_problems: List[EnvironmentalProblem] = Field(default_factory=list)
    overall_direction: OverallDirection = "insufficient_history"
    #: Mirrors the deterministic Coordinator. The decision NEVER recomputes risk.
    risk_level: RiskLevel = "LOW"
    risk_score: float = Field(default=0.0, ge=0, le=1)
    confidence: float = Field(default=0.0, ge=0, le=1)
    sufficient_evidence: bool = False
    evidence: List[EnvironmentalEvidence] = Field(default_factory=list)
    cross_signal_findings: List[CrossSignalFinding] = Field(default_factory=list)
    conflicts: List[EvidenceConflict] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    data_gaps: List[str] = Field(default_factory=list)
    investigation_plan: List[InvestigationAction] = Field(default_factory=list)
    decision_trace: List[DecisionTraceStep] = Field(default_factory=list)
    triage: TriageDecision = Field(default_factory=TriageDecision)
    #: Always present and always deterministic.
    explanation: str = ""
    #: Evidence-supported reasons, ranked and never padded to a target count.
    reasons: List["DeteriorationReason"] = Field(default_factory=list)
    #: Actions derived from the detected problems, with planning horizons.
    recovery: Optional["RecoveryPlan"] = None
    #: Functional-AI contribution, when a functional provider ran. Enters as evidence, not verdict.
    functional_analysis: Optional["FunctionalAnalysis"] = None
    #: Optional LLM prose. Additive only — it never replaces `explanation`.
    llm_explanation: Optional[str] = None
    llm_enhanced: bool = False
    #: Which explainability provider wrote `llm_explanation`, for provenance.
    explanation_provider: Optional[str] = None
    data_status: Literal["live", "demo", "mixed", "none"] = "none"
    #: Knowledge retrieved to ground the explanation. Context only — see RetrievedKnowledge.
    knowledge: KnowledgeRetrieval = Field(default_factory=KnowledgeRetrieval)


# ---------------------------------------------------------------- frame investigation
#
# What the Water page shows after a user clicks a frame: WHERE the visible pollution is, WHY it
# matters, and WHAT to do next. Every field is derived from what a detector actually returned —
# there is no path here that invents a detection, a reason, a coordinate or a date.

#: How much the evidence actually supports a reason. The distinction is the point: an image can
#: show floating plastic (OBSERVED) but can never establish chemical contamination.
ReasonType = Literal["OBSERVED", "INFERRED", "HYPOTHESIS", "UNKNOWN"]


class FrameDetection(ApiModel):
    """One object the vision model located in the selected frame.

    `image_region` describes a position WITHIN THE FRAME ("lower-left foreground"), never a
    real-world location. The model knows where something sits in an image; it knows nothing about
    where that is on the ground.
    """

    detection_id: str            # IMG-DET-001
    class_name: str              # exactly what the model reported, never remapped
    confidence: float = Field(ge=0, le=1)
    #: Pixel-space corners as the detector returned them.
    bbox: List[float] = Field(min_length=4, max_length=4)
    #: Same box normalised to 0..1 of the frame, so the UI can overlay it at any display size.
    bbox_relative: List[float] = Field(default_factory=list)
    image_region: Optional[str] = None


class InvestigationReason(ApiModel):
    """One reason this frame is a concern, with its evidence and how strongly it is supported."""

    reason_id: str               # WHY-001
    text: str
    type: ReasonType
    evidence_ids: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    observed_at: Optional[datetime] = None


class FrameAction(ApiModel):
    """One recommended action for a clicked frame, tied to the evidence that motivates it.

    Distinct from `InvestigationAction`, which the decision engine uses for "what data to collect
    next". This is "what to do about what was seen".
    """

    action_id: str               # ACTION-001
    action: str
    rationale: str
    priority: Literal["high", "medium", "low"]
    expected_effect: str
    timeframe: str               # e.g. "0-7 days"
    timeline_category: Literal["immediate", "short_term", "medium_term", "long_term"]
    evidence_ids: List[str] = Field(default_factory=list)


class EscalationRisk(ApiModel):
    """How the observed situation could get worse if nothing is done.

    These are PROJECTIONS, not observations and not predictions. Each one is tied to evidence that
    actually exists in the frame, and none of them asserts that the outcome will occur — the
    wording stays conditional ("if left in place", "could", "risks") because a single photograph
    cannot establish what will happen next.
    """

    risk_id: str                 # WORSE-001
    text: str
    #: What in this frame makes the projection plausible.
    evidence_ids: List[str] = Field(default_factory=list)
    #: How soon it could plausibly develop, as a planning horizon.
    horizon: Literal["immediate", "short_term", "medium_term", "long_term"] = "short_term"
    #: Always "projection". Fixed so no caller can present one of these as an observation.
    basis: Literal["projection"] = "projection"


class RecoveryTimeline(ApiModel):
    """Planning horizons. Explicitly NOT a prediction of ecological recovery."""

    immediate: str = "0-7 days"
    short_term: str = "1-4 weeks"
    medium_term: str = "1-3 months"
    long_term: str = "3-12+ months"
    is_estimate: bool = True
    caveat: str = (
        "Estimated planning timeline - actual environmental recovery depends on pollution source, "
        "waste load, hydrology, remediation effectiveness, and continued monitoring."
    )
    #: Set when there is no historical evidence to support any trend statement at all.
    trend_note: Optional[str] = None


class InvestigationGeotag(ApiModel):
    """Where the frame was captured, when the device could say.

    Every field is optional and nothing is ever inferred. A denied permission leaves this
    `available=False` with a reason, and the visual analysis proceeds unchanged — a location is
    provenance, never an input to the score.
    """

    available: bool = False
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    accuracy_meters: Optional[float] = Field(default=None, ge=0)
    captured_at: Optional[datetime] = None
    source: Optional[Literal["browser", "manual", "preset"]] = None
    resolved_name: Optional[str] = None
    message: Optional[str] = None


class DataAvailability(ApiModel):
    """Which kinds of evidence this investigation actually has.

    Stated explicitly because "no measurements" and "measurements were fine" look identical in a
    report that simply omits them. A frame can carry strong visual evidence and no water
    chemistry at all, and the reader needs to see that distinction.
    """

    visual: bool = False
    water_measurements: bool = False
    detail: Optional[str] = None


class FrameInvestigation(ApiModel):
    """The full explainable-AI report for one clicked frame."""

    investigation_id: str
    data_availability: DataAvailability = Field(default_factory=DataAvailability)
    summary: str
    #: True only when the detector actually ran and returned boxes.
    detections_available: bool = False
    detection_status: str = "not_run"
    detection_message: Optional[str] = None
    model: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    detections: List[FrameDetection] = Field(default_factory=list)
    reasons: List[InvestigationReason] = Field(default_factory=list)
    actions: List[FrameAction] = Field(default_factory=list)
    #: How this could deteriorate if nothing is done. Projections, never predictions.
    escalation_risks: List[EscalationRisk] = Field(default_factory=list)
    timeline: RecoveryTimeline = Field(default_factory=RecoveryTimeline)
    geotag: InvestigationGeotag = Field(default_factory=InvestigationGeotag)
    captured_at: Optional[datetime] = None
    #: Plain-language reasoning about THIS frame, written by the explainability provider from the
    #: detection counts and classes above. Additive only — it never changes a count, a box or a
    #: score, and its absence costs nothing because `summary` and `reasons` are always present.
    llm_reasoning: Optional[str] = None
    explanation_provider: Optional[str] = None


# ---------------------------------------------------------------- AI provider roles
#
# Two LLM roles that are NOT interchangeable:
#   FUNCTIONAL (Gemini)              performs AI work whose output becomes EVIDENCE, validated
#                                    against these schemas before the engine sees it.
#   EXPLAINABILITY (OpenRouter/Groq) receives an already-final decision and puts it into words.
#
# The split exists because a model asked to explain a decision, and a model trusted to produce
# one, need very different guarantees.


class FunctionalObservation(ApiModel):
    """One thing the functional AI claims to observe. Enters the pipeline as evidence."""

    type: str = Field(max_length=60)
    description: str = Field(max_length=400)
    confidence: float = Field(ge=0, le=1)


class FunctionalAnalysis(ApiModel):
    """Validated functional-AI output.

    `uncertainties` is required by the prompt and kept in the contract, because the useful part
    of a vision model's answer is often what it says it cannot tell you — an image can show
    floating plastic but can never establish chemical contamination.
    """

    available: bool = False
    status: Literal["ok", "not_run", "not_configured", "unavailable", "invalid_response"] = "not_run"
    provider: Optional[str] = None
    model: Optional[str] = None
    message: Optional[str] = None
    observations: List[FunctionalObservation] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class DeteriorationReason(ApiModel):
    """One evidence-supported reason. Never produced without evidence ids behind it."""

    rank: int
    title: str
    detail: str
    evidence_ids: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    domain: Literal["air", "water", "waste", "geographic", "unknown"] = "unknown"


class RecoveryAction(ApiModel):
    """An action that follows from a detected problem, in a planning horizon."""

    rank: int
    title: str
    addresses_problem: str
    evidence_ids: List[str] = Field(default_factory=list)
    timeline_category: Literal["immediate", "short_term", "medium_term", "long_term"]
    timeline_range: str


class RecoveryPlan(ApiModel):
    """Planning horizons, explicitly not a prediction of when recovery will occur."""

    available: bool = False
    actions: List[RecoveryAction] = Field(default_factory=list)
    timeline_category: Literal["immediate", "short_term", "medium_term", "long_term"] = "short_term"
    timeline_range: str = ""
    summary: str = ""


class AiRoleStatus(ApiModel):
    """One AI role's health. Never carries a key, or any prefix or suffix of one."""

    provider: str = "none"
    configured: bool = False
    available: bool = False
    model: Optional[str] = None
    detail: Optional[str] = None


class ToolDescriptor(ApiModel):
    """One registered tool, as the API advertises it."""

    name: str
    description: str
    category: str
    read_only: bool = True
    #: JSON Schema for the tool's arguments, so the tool is genuinely model-callable.
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ToolListResponse(ApiModel):
    tools: List[ToolDescriptor] = Field(default_factory=list)
    count: int = 0
    #: The boundary this layer exists to enforce, restated where callers will read it.
    contract: str = (
        "A model may decide which tool to call and with what arguments. The tool decides what "
        "the answer is. Deterministic values are computed in Python, never produced by a model."
    )


class ToolInvokeRequest(ApiModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolInvokeResponse(ApiModel):
    tool: str
    ok: bool
    duration_ms: int = 0
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    #: UNKNOWN_TOOL | INVALID_ARGUMENTS | TOOL_FAILED | and tool-specific codes.
    error_code: Optional[str] = None


class KnowledgeSearchRequest(ApiModel):
    """Free-text query against the knowledge corpus."""

    query: str = Field(min_length=1, max_length=400)
    top_k: int = Field(default=3, ge=1, le=10)
    #: Optional domain bias (air | water | waste | cross_signal). Boosts, never filters.
    domain: Optional[str] = Field(default=None, max_length=40)


class KnowledgeStatus(ApiModel):
    """Health of the retrieval corpus, reported alongside the AI roles.

    Retrieval is a distinct capability from either LLM role: it supplies grounding passages and
    holds no opinion, so it is reported separately rather than folded into explainability.
    """

    available: bool = False
    documents: int = 0
    chunks: int = 0
    vocabulary: int = 0
    #: Stated plainly rather than implying a semantic model is running.
    embedding: str = "tfidf-sparse-lexical"
    top_k: Optional[int] = None
    min_score: Optional[float] = None
    document_ids: List[str] = Field(default_factory=list)
    detail: Optional[str] = None


class AiStatusResponse(ApiModel):
    functional_ai: AiRoleStatus
    explainable_ai: AiRoleStatus
    #: Visual object localization. A separate role from either LLM: YOLO locates objects, and
    #: neither AI provider may substitute for it.
    vision: AiRoleStatus = Field(default_factory=AiRoleStatus)
    #: Retrieval corpus health. Not an LLM role — it retrieves, it does not generate.
    knowledge: KnowledgeStatus = Field(default_factory=KnowledgeStatus)


class FrameScanVerdict(ApiModel):
    """The live camera's entire output: is there visible contamination, yes or no.

    Deliberately minimal. While a camera is running, a full investigation per frame would be
    expensive, would narrate footage nobody chose, and would train people to ignore the alert.
    The detailed work happens once, on a frame the user deliberately picks.
    """

    status: Literal["ok", "not_run", "model_not_configured", "unavailable"] = "not_run"
    #: True only when the detector returned at least one POLLUTION-relevant class.
    contaminated: bool = False
    #: Pollution-relevant detections only.
    object_count: int = 0
    #: Everything else the detector saw, reported separately so a person is never counted as litter.
    other_object_count: int = 0
    classes: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    message: Optional[str] = None


class WasteXaiAttribution(ApiModel):
    """Gradient attribution for one classification.

    Explains the CLASSIFIER's answer about one crop. It says nothing about the detector's box,
    and nothing about the segregation category, which is a configured policy mapping rather than
    a model output.
    """

    method: str = "grad-cam"
    available: bool = False
    #: Reason, when `available` is false. Never a substitute image.
    message: Optional[str] = None
    #: The class the attribution explains, and the model's confidence in it.
    target_class: Optional[str] = None
    target_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    #: The layer gradients were taken at.
    layer: Optional[str] = None
    #: The spatial grid the attribution was actually computed on, e.g. "7x7". Recorded so an
    #: upsampled overlay is never read as pixel-level precision.
    attribution_grid: Optional[str] = None
    overlay_image: Optional[str] = None  # data URI


class WasteSegregationDetection(ApiModel):
    """One detected object, with the two stages reported separately.

    `detected_object` is the DETECTOR's class, exactly as reported. `classification` is the
    segregation model's verdict on the crop. They are different models answering different
    questions, so a COCO detector saying "cup" and the classifier saying "metal_cans" is a normal,
    informative result rather than a contradiction to be hidden.
    """

    id: str
    bbox: List[float] = Field(min_length=4, max_length=4)
    detected_object: str
    detection_confidence: float = Field(ge=0, le=1)
    classification: Optional[str] = None
    classification_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    segregation: Literal["biodegradable", "non_biodegradable", "uncertain"] = "uncertain"
    status: Literal["confirmed", "needs_review", "unavailable"] = "needs_review"
    #: Top class when confidence was below threshold. Visible for review, never a decision.
    candidate: Optional[str] = None
    handling: Optional[str] = None
    display: Optional[str] = None
    #: Application-level policy note, deliberately separate from the model's prediction.
    environmental_note: Optional[str] = None
    #: Other class names the detector gave to this same region, absorbed as duplicates. Kept
    #: visible because it is the detector's own uncertainty, not noise to be swept away.
    also_detected_as: Optional[List[str]] = None
    #: Which stage produced `classification`. `detector` when the detector emitted a waste class
    #: and the classifier did not confirm the same name; `classifier` when the two agree or when
    #: only the classifier can name the object (COCO detectors).
    label_source: Optional[Literal["detector", "classifier"]] = None
    #: Why the localisation was refused before the crop was ever classified, when it was.
    #: `degenerate_box` — the box spans almost the whole frame in both axes, so it localises a
    #: region rather than an object. `non_waste_object` — a general-purpose detector identified
    #: the same region as something that cannot be litter. The detection is still reported; only
    #: the segregation claim is withheld, and `candidate` carries the detector's class.
    localisation_rejected: Optional[Literal["degenerate_box", "non_waste_object"]] = None
    message: Optional[str] = None
    #: Grad-CAM attribution over the classifier's own prediction, when it was requested and could
    #: be computed. Absent by default: it costs a backward pass per crop and is a diagnostic, not
    #: part of the decision. When present and `available` is false it carries the reason — an
    #: explanation is either the model's real gradients or nothing.
    xai: Optional[WasteXaiAttribution] = None


class WasteSegregationSummary(ApiModel):
    total_objects: int = 0
    biodegradable: int = 0
    non_biodegradable: int = 0
    #: Counted on its own. Folding uncertain into either bucket hides what needs review.
    uncertain: int = 0
    #: Overlapping boxes merged into another object. `total_objects` is the count after merging,
    #: and this says how much merging it took to get there.
    duplicate_boxes_merged: int = 0
    #: Detected objects whose class rules out waste entirely (a person, a car). Counted so a
    #: reader can see that some of `total_objects` are not litter.
    non_waste_objects: int = 0
    #: Boxes refused by the localisation gate before any classification was attempted, for any
    #: reason. Reported rather than hidden: "the detector found nothing" and "it found three
    #: things and all three were refused" are very different states of the world.
    localisations_rejected: int = 0


class WasteSegregationResult(ApiModel):
    """Two-stage waste analysis: detection, then segregation classification."""

    status: str = "not_run"
    model: Optional[str] = None
    classifier_available: bool = False
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    detections: List[WasteSegregationDetection] = Field(default_factory=list)
    summary: WasteSegregationSummary = Field(default_factory=WasteSegregationSummary)
    message: Optional[str] = None


class GeminiWasteDetection(ApiModel):
    """One object Gemini reported, mapped onto the existing taxonomy.

    `confidence` is always None. Gemini returns a label, not a calibrated score, and a number
    invented here would be compared against YOLO's real one.
    """

    canonical_class: str
    class_id: Optional[int] = None
    label: Optional[str] = None
    #: As Gemini returned it: [ymin, xmin, ymax, xmax] over 0..1000. Kept for traceability.
    box_2d: List[float] = Field(default_factory=list)
    #: Converted to the application's convention: [x1, y1, x2, y2] in pixels.
    bbox: List[float] = Field(default_factory=list)
    confidence: Optional[float] = None


class GeminiWasteRejection(ApiModel):
    """A detection that failed validation, kept with its reason rather than dropped silently."""

    index: Optional[int] = None
    reason: Optional[str] = None
    class_name: Optional[str] = Field(default=None, alias="class")
    raw: Optional[str] = None


class GeminiWasteResult(ApiModel):
    """EXPERIMENTAL. Gemini's reading of one image. Not the production detector."""

    provider: str = "gemini"
    model: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    detections: List[GeminiWasteDetection] = Field(default_factory=list)
    rejected: List[GeminiWasteRejection] = Field(default_factory=list)
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    candidate: Optional[dict] = None


class WastePipelineStatus(ApiModel):
    """Health of each stage, reported separately — either can be missing on its own."""

    detector: AiRoleStatus = Field(default_factory=AiRoleStatus)
    classifier_configured: bool = False
    classifier_available: bool = False
    classifier_classes: List[str] = Field(default_factory=list)
    classification_threshold: Optional[float] = None
    detail: Optional[str] = None


class ChatRequest(ApiModel):
    """A question about one specific analysis.

    `analysis_id` is required: an answer must be grounded in the decision the user is looking at.
    Without it the backend would have to guess which analysis "this river" means, and guessing is
    how River A's evidence ends up explaining River B.
    """

    analysis_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=500)


class ChatToolExecution(ApiModel):
    """One tool call the chat agent made, as the UI shows it.

    Deliberately shallow: tool name, why it ran, whether it worked, and a one-line summary of the
    result. No prompt, no routing rationale and no model reasoning is exposed — those are not
    verifiable by a reader, whereas "this tool ran and returned this" is.
    """

    tool: str
    purpose: str
    status: Literal["ok", "failed"] = "ok"
    duration_ms: int = 0
    summary: str = ""
    error: Optional[str] = None


class ChatCitation(ApiModel):
    """A retrieved passage backing an answer. Always a real chunk from the real retriever."""

    chunk_id: str
    document_title: str
    section: str
    source_file: Optional[str] = None
    score: float = 0.0
    content: str = ""


class ChatResponse(ApiModel):
    analysis_id: str
    question: str
    answer: str
    #: Evidence ids the answer rests on, so any claim can be checked against the decision.
    evidence_ids: List[str] = Field(default_factory=list)
    #: "deterministic" when no explainability provider ran, else the provider name.
    source: str = "deterministic"
    llm_enhanced: bool = False
    #: How the message was routed. `unavailable` means no provider could serve it.
    intent: Literal["analysis", "functional", "general", "unavailable"] = "analysis"
    #: Tools that actually ran, in order.
    tool_executions: List[ChatToolExecution] = Field(default_factory=list)
    #: Retrieved passages backing the answer, each resolving to a real corpus chunk.
    citations: List[ChatCitation] = Field(default_factory=list)


# ---------------------------------------------------------------- orchestration


class AgentRun(ApiModel):
    agent: AgentId
    name: str
    status: Literal["complete", "failed", "timeout"]
    duration_ms: int
    steps: List[str]
    error: Optional[str] = None


class AnalysisResult(ApiModel):
    analysis_id: str
    location: str
    mode: Literal["demo", "live"]
    started_at: datetime
    completed_at: datetime
    air: Optional[AirAgentResult]
    water: Optional[WaterAgentResult]
    waste: Optional[WasteAgentResult]
    coordinator: CoordinatorResult
    runs: List[AgentRun]
    location_context: Optional[LocationContext] = None
    #: Optional OSM enrichment. Descriptive context only — it never influenced `coordinator`.
    geographic_context: Optional[GeographicContext] = None
    #: The LangGraph decision engine's output. `coordinator` remains the deterministic risk
    #: authority; `decision` explains what the evidence points to and what to investigate next.
    decision: Optional[EnvironmentalDecision] = None
    #: Clicked-frame report, when a frame was investigated. Present even if the water specialist
    #: produced nothing — visual evidence stands on its own.
    investigation: Optional["FrameInvestigation"] = None


class WasteImageAnalysis(ApiModel):
    waste: WasteAgentResult
    coordinator: Optional[CoordinatorResult]
    runs: List[AgentRun]


class ContaminationReportRequest(ApiModel):
    """A citizen report of an apparently contaminated water body.

    PRIVACY: unlike every other endpoint, submitting this DOES persist the precise coordinates the
    reporter chose to attach — that is the point of a report. It is only ever sent on an explicit
    per-report confirmation in the UI.
    """

    location: LocationContext
    match: WaterDatasetMatch
    observed_at: datetime
    source: Literal["upload", "camera"] = "upload"
    note: Optional[str] = Field(default=None, max_length=1000)
    contact: Optional[str] = Field(default=None, max_length=200)
    water_risk_level: Optional[RiskLevel] = None
    water_risk_score: Optional[float] = Field(default=None, ge=0, le=1)
    #: Evidence frame as a data URI. Stored next to the report when present.
    photo: Optional[str] = Field(default=None, max_length=8_000_000)


class ContaminationReportReceipt(ApiModel):
    """What actually happened to a submitted report — never more than that.

    `recorded` means it was written to this backend's report log only. `forwarded` is returned
    only when a configured destination accepted it. Nothing here implies an authority has seen a
    report unless `delivered_to` names where it went.
    """

    reference: str
    status: Literal["recorded", "forwarded", "forward_failed"]
    message: str
    created_at: datetime
    stored: bool
    delivered_to: Optional[str] = None
    summary: str


class AnalyzeRequest(ApiModel):
    location: Optional[str] = Field(default=None, min_length=1, max_length=80)
    location_context: Optional[LocationContext] = None
    demo_mode: bool = True

    @model_validator(mode="after")
    def _require_location(self) -> "AnalyzeRequest":
        if self.location is None and self.location_context is None:
            raise ValueError("Provide a location name or a location context.")
        return self


class EnvironmentRequest(ApiModel):
    location_context: LocationContext


class WaterReadingIngest(ApiModel):
    ph: Optional[float] = Field(default=None, allow_inf_nan=False)
    turbidity: Optional[float] = Field(default=None, allow_inf_nan=False)
    temperature: Optional[float] = Field(default=None, allow_inf_nan=False)
    tds: Optional[float] = Field(default=None, allow_inf_nan=False)
    observed_at: Optional[datetime] = None


# ---------------------------------------------------------------- environment


class LocationInfo(ApiModel):
    id: str
    name: str
    region: str
    lat: float
    lon: float


class MapStation(ApiModel):
    id: str
    type: SpecialistAgentId
    label: str
    x: float
    y: float
    primary: bool = False
    risk_factor: float = 1.0


class WaterBody(ApiModel):
    x: float
    y: float
    rx: float
    ry: float


class TrendPoint(ApiModel):
    hours_ago: int
    timestamp: datetime
    pm25: Optional[float]
    turbidity: Optional[float]
    waste_count: int


class EnvironmentSnapshot(ApiModel):
    location: LocationInfo
    stations: List[MapStation]
    water_bodies: List[WaterBody]
    history: Dict[str, List[TrendPoint]]


class AgentStatus(ApiModel):
    id: AgentId
    name: str
    status: Literal["operational", "degraded", "offline"]
    provider: str
    last_run_at: Optional[datetime] = None
    last_duration_ms: Optional[int] = None


class AgentsStatusResponse(ApiModel):
    operational: bool
    summary: str
    agents: List[AgentStatus]
