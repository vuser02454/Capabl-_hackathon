"""The tools themselves.

Each one wraps an implementation that already exists and is already tested. None of them
re-implements logic, because a tool layer that reproduces the pipeline is a second pipeline that
can quietly disagree with the first.

Read the docstrings as contracts: several say explicitly what the tool cannot establish, and
those sentences are load-bearing. `analyze_water_image` returning "3 litter objects" is a claim
about a surface; a caller that reads it as a claim about chemistry has been misled, and the tool
description is the last place to prevent that.
"""

from typing import Any, Dict, List, Optional

from pydantic import Field

from schemas import ApiModel
from services.tools.registry import Tool, ToolError, registry

# --------------------------------------------------------------------------- shared models


class LocationInput(ApiModel):
    location: str = Field(
        description="Place name, e.g. 'Delhi' or 'Bengaluru'.", min_length=1, max_length=120
    )
    demo_mode: bool = Field(
        default=True,
        description="True uses seeded demo providers; False uses live providers where configured.",
    )


def _resolve(location: str):
    from core.errors import EcoSentinelError
    from services.location_service import resolve_location

    try:
        return resolve_location(location, None)
    except EcoSentinelError as exc:
        raise ToolError(exc.message, code="UNKNOWN_LOCATION") from exc


# --------------------------------------------------------------------------- air


class AirQualityOutput(ApiModel):
    location: str
    risk_level: str
    risk_score: float
    confidence: float
    aqi_estimate: Optional[float] = None
    aqi_category: Optional[str] = None
    measurements: List[Dict[str, Any]] = Field(default_factory=list)
    data_source: str
    is_mock: bool
    anomalies: List[str] = Field(default_factory=list)


def _get_air_quality_data(payload: LocationInput) -> AirQualityOutput:
    from agents.base import AgentTrace
    from agents.orchestrator import build_agents
    from core.errors import EcoSentinelError

    air, _water, _waste, _coordinator = build_agents(payload.demo_mode)
    try:
        report = air.run(_resolve(payload.location), AgentTrace())
    except EcoSentinelError as exc:
        raise ToolError(exc.message, code="PROVIDER_UNAVAILABLE") from exc

    return AirQualityOutput(
        location=report.location,
        risk_level=report.risk_level,
        risk_score=report.risk_score,
        confidence=report.confidence,
        aqi_estimate=getattr(report, "aqi", None),
        aqi_category=getattr(report, "aqi_category", None),
        measurements=[m.model_dump(by_alias=True, mode="json") for m in report.measurements],
        data_source=report.data_source,
        is_mock=report.is_mock,
        anomalies=list(report.anomalies),
    )


registry.register(Tool(
    name="get_air_quality_data",
    description=(
        "Fetch air-quality measurements for a named location: PM2.5, PM10, NO2 and O3 against "
        "WHO 2021 guidelines, plus a deterministic risk score and an India NAQI estimate. "
        "The NAQI figure is an ESTIMATE because it is computed from single readings rather than "
        "a 24-hour average. Returns measured values only — it does not interpret them."
    ),
    input_model=LocationInput,
    output_model=AirQualityOutput,
    handler=_get_air_quality_data,
    category="air",
))


# --------------------------------------------------------------------------- water sensors


class WaterSensorOutput(ApiModel):
    location: str
    sensor_id: str
    sensor_name: str
    source_type: str
    risk_level: str
    risk_score: float
    confidence: float
    ph: Optional[float] = None
    turbidity: Optional[float] = None
    temperature: Optional[float] = None
    tds: Optional[float] = None
    measurements: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    is_mock: bool
    data_age_minutes: Optional[int] = None


def _get_water_sensor_data(payload: LocationInput) -> WaterSensorOutput:
    from agents.base import AgentTrace
    from agents.water_agent import WaterQualityAgent
    from core.errors import EcoSentinelError
    from services.water_sensor_service import get_water_provider

    agent = WaterQualityAgent(get_water_provider(payload.demo_mode))
    try:
        report = agent.run(_resolve(payload.location), AgentTrace())
    except EcoSentinelError as exc:
        raise ToolError(exc.message, code="SENSOR_UNAVAILABLE") from exc

    return WaterSensorOutput(
        location=report.location,
        sensor_id=report.sensor_id,
        sensor_name=report.sensor_name,
        source_type=report.source_type,
        risk_level=report.risk_level,
        risk_score=report.risk_score,
        confidence=report.confidence,
        ph=report.ph,
        turbidity=report.turbidity,
        temperature=report.temperature,
        tds=report.tds,
        measurements=[m.model_dump(by_alias=True, mode="json") for m in report.measurements],
        warnings=list(report.warnings),
        is_mock=report.is_mock,
        data_age_minutes=report.data_age_minutes,
    )


registry.register(Tool(
    name="get_water_sensor_data",
    description=(
        "Fetch measured water-quality parameters for a location: pH, turbidity, temperature and "
        "TDS against BIS 10500 limits, with a deterministic water-quality risk score. Resolves "
        "the nearest IoT sensor, then monitoring station, then dataset, then demo data, and "
        "reports which was used. These are the ONLY water parameters the system measures — it "
        "does not measure dissolved oxygen, BOD, COD, heavy metals or pathogens."
    ),
    input_model=LocationInput,
    output_model=WaterSensorOutput,
    handler=_get_water_sensor_data,
    category="water",
))


# --------------------------------------------------------------------------- water vision


class ImageInput(ApiModel):
    image_base64: str = Field(description="Base64-encoded image bytes.", min_length=16)
    filename: str = Field(default="image.jpg", max_length=200)


class WaterVisionOutput(ApiModel):
    status: str
    model: Optional[str] = None
    total_objects: int = 0
    pollution_objects: int = 0
    non_pollution_objects: int = 0
    visual_score: Optional[float] = None
    detections: List[Dict[str, Any]] = Field(default_factory=list)
    message: Optional[str] = None
    #: Restated on every response because this is the claim most easily over-read.
    establishes: str = (
        "Visible surface litter only. This tool cannot establish pH, dissolved oxygen, chemical "
        "contamination or potability, and absence of litter is not evidence that water is clean."
    )


def _decode(payload: ImageInput) -> bytes:
    import base64
    import binascii

    try:
        return base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError("image_base64 is not valid base64.", code="INVALID_IMAGE") from exc


def _analyze_water_image(payload: ImageInput) -> WaterVisionOutput:
    from services.water_vision_service import build_report, get_water_vision_detector

    report = build_report(get_water_vision_detector(), _decode(payload), payload.filename)
    return WaterVisionOutput(
        status=report.status,
        model=report.model,
        total_objects=report.total_objects,
        pollution_objects=report.pollution_objects,
        non_pollution_objects=report.non_pollution_objects,
        visual_score=report.visual_score,
        detections=[d.model_dump(by_alias=True, mode="json") for d in report.detections],
        message=report.message,
    )


registry.register(Tool(
    name="analyze_water_image",
    description=(
        "Detect visible objects in a water photograph and classify each as visible surface "
        "litter, a non-pollution object, or unclassified. Returns every detection with its raw "
        "detector class, its semantic category and a confidence. Only litter contributes to the "
        "visual pollution score. IMPORTANT: this establishes a surface condition, never "
        "chemistry — it cannot determine pH, dissolved oxygen, contamination or potability."
    ),
    input_model=ImageInput,
    output_model=WaterVisionOutput,
    handler=_analyze_water_image,
    category="water",
))


# --------------------------------------------------------------------------- waste vision


class WasteImageInput(ImageInput):
    explain: bool = Field(
        default=False,
        description="Include a Grad-CAM attribution per classified crop. Costs a backward pass per object.",
    )


class WasteAnalysisOutput(ApiModel):
    status: str
    model: Optional[str] = None
    classifier_available: bool = False
    detections: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None


def _analyze_waste_image(payload: WasteImageInput) -> WasteAnalysisOutput:
    from services.waste.waste_pipeline import analyze_waste

    result = analyze_waste(
        _decode(payload), payload.filename, None, None, None, payload.explain
    )
    return WasteAnalysisOutput(
        status=result["status"],
        model=result.get("model"),
        classifier_available=result.get("classifier_available", False),
        detections=result.get("detections", []),
        summary=result.get("summary", {}),
        message=result.get("message"),
    )


registry.register(Tool(
    name="analyze_waste_image",
    description=(
        "Two-stage waste analysis of a photograph: YOLO detection, then an 8-class classifier on "
        "each crop, then a 0.60 confidence gate. Returns each object's detector class, "
        "classification, confidence, segregation category and status. A result below the gate is "
        "returned as 'needs_review' with the label as a candidate and NO segregation asserted — "
        "that is a real answer, not a failure. Optionally includes Grad-CAM attribution."
    ),
    input_model=WasteImageInput,
    output_model=WasteAnalysisOutput,
    handler=_analyze_waste_image,
    category="waste",
))


# --------------------------------------------------------------------------- segregation


class SegregationInput(ApiModel):
    material: str = Field(
        description="A waste class name, e.g. 'plastic_bottles', 'paper_waste', 'ewaste'.",
        min_length=1, max_length=60,
    )


class SegregationOutput(ApiModel):
    material: str
    known: bool
    display: Optional[str] = None
    category: Optional[str] = None
    handling: Optional[str] = None
    environmental_note: Optional[str] = None
    recovery_actions: List[Dict[str, str]] = Field(default_factory=list)
    message: Optional[str] = None


def _get_waste_segregation_guidance(payload: SegregationInput) -> SegregationOutput:
    from core.recovery import CATEGORY_ACTIONS, TIMELINE_BANDS
    from services.waste.waste_classifier import ClassifierUnavailable, get_waste_classifier

    try:
        classifier = get_waste_classifier()
        config = classifier.config
    except ClassifierUnavailable as exc:
        raise ToolError(exc.message, code="CONFIG_UNAVAILABLE") from exc

    material = payload.material.strip().lower()
    entry = (config.get("classes") or {}).get(material)
    if not entry:
        known = ", ".join(sorted((config.get("classes") or {}).keys()))
        return SegregationOutput(
            material=material, known=False,
            message=f"'{material}' is not one of the configured waste classes. Known classes: {known}.",
        )

    handling = entry.get("handling")
    return SegregationOutput(
        material=material,
        known=True,
        display=entry.get("display"),
        category=entry.get("category"),
        handling=handling,
        environmental_note=(config.get("handling_notes") or {}).get(handling),
        recovery_actions=[
            {"action": action, "horizon": TIMELINE_BANDS.get(band, band)}
            for action, band in CATEGORY_ACTIONS.get("waste", [])
        ],
    )


registry.register(Tool(
    name="get_waste_segregation_guidance",
    description=(
        "Look up the segregation category, handling route and environmental note for a waste "
        "class, plus the configured recovery actions with their planning horizons. Values come "
        "from training/config/waste_categories.json and core/recovery.py — they are configured "
        "municipal policy, not model predictions, and horizons are planning bands rather than "
        "predicted dates. An unknown material returns known=false with the valid class list."
    ),
    input_model=SegregationInput,
    output_model=SegregationOutput,
    handler=_get_waste_segregation_guidance,
    category="waste",
))


# --------------------------------------------------------------------------- location


class LocationContextOutput(ApiModel):
    label: str
    latitude: float
    longitude: float
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    water_feature: Optional[str] = None
    geographic_available: bool = False
    industrial_features: int = 0
    waste_facilities: int = 0
    waterways: int = 0
    roads: int = 0
    nearest_feature: Optional[str] = None
    note: str = (
        "Geographic features are mapped OpenStreetMap objects. They are CONTEXT only: a mapped "
        "factory is not an emission and never contributes to a risk score."
    )


def _get_location_context(payload: LocationInput) -> LocationContextOutput:
    from services.location_service import location_label, resolve_geographic_context

    context = _resolve(payload.location)
    geographic = resolve_geographic_context(context)

    nearest = None
    groups = (
        geographic.industrial_features, geographic.waste_facilities,
        geographic.waterways, geographic.roads,
    ) if geographic and geographic.available else ()
    candidates = [feature for group in groups for feature in group]
    if candidates:
        closest = min(candidates, key=lambda f: f.distance_km)
        nearest = f"{closest.name or closest.label} ({closest.distance_km:.2f} km)"

    return LocationContextOutput(
        label=location_label(context),
        latitude=context.latitude,
        longitude=context.longitude,
        city=context.city,
        state=context.state,
        country=context.country,
        water_feature=context.water_feature,
        geographic_available=bool(geographic and geographic.available),
        industrial_features=len(geographic.industrial_features) if geographic else 0,
        waste_facilities=len(geographic.waste_facilities) if geographic else 0,
        waterways=len(geographic.waterways) if geographic else 0,
        roads=len(geographic.roads) if geographic else 0,
        nearest_feature=nearest,
    )


registry.register(Tool(
    name="get_location_context",
    description=(
        "Resolve a place name to coordinates and administrative details, and count nearby mapped "
        "OpenStreetMap features (industrial sites, waste facilities, waterways, major roads). "
        "Geographic features are contextual enrichment ONLY — they carry no severity and never "
        "contribute to a pollution measurement or a risk score."
    ),
    input_model=LocationInput,
    output_model=LocationContextOutput,
    handler=_get_location_context,
    category="location",
))


# --------------------------------------------------------------------------- knowledge


class KnowledgeSearchInput(ApiModel):
    query: str = Field(description="What to look up.", min_length=1, max_length=400)
    top_k: int = Field(default=3, ge=1, le=10)
    domain: Optional[str] = Field(
        default=None, description="Optional bias: air | water | waste | cross_signal.", max_length=40
    )


class KnowledgeSearchOutput(ApiModel):
    query: str
    results: List[Dict[str, Any]] = Field(default_factory=list)
    message: Optional[str] = None


def _search_environmental_knowledge(payload: KnowledgeSearchInput) -> KnowledgeSearchOutput:
    from services import rag

    results = rag.search_knowledge(payload.query, top_k=payload.top_k, domain=payload.domain)
    return KnowledgeSearchOutput(
        query=payload.query,
        results=[
            {
                "chunkId": r.chunk_id,
                "documentTitle": r.document_title,
                "section": r.section,
                "sourceFile": r.source,
                "score": r.score,
                "content": r.text,
            }
            for r in results
        ],
        message=None if results else (
            "No corpus passage cleared the relevance floor. The knowledge base does not cover "
            "this question — do not answer it from general knowledge and present it as sourced."
        ),
    )


registry.register(Tool(
    name="search_environmental_knowledge",
    description=(
        "Search EcoSentinel's knowledge corpus for passages about thresholds, standards, "
        "segregation policy, recovery horizons, evidence semantics and measured model limits. "
        "Every result carries a chunk id and the repository file it came from, so any citation "
        "can be checked. Returns NOTHING when the corpus does not cover the question — treat an "
        "empty result as 'this system has no documented basis for that', never as licence to "
        "answer from general knowledge."
    ),
    input_model=KnowledgeSearchInput,
    output_model=KnowledgeSearchOutput,
    handler=_search_environmental_knowledge,
    category="knowledge",
))


# --------------------------------------------------------------------------- risk


class RiskInput(ApiModel):
    air_score: Optional[float] = Field(default=None, ge=0, le=1)
    water_score: Optional[float] = Field(default=None, ge=0, le=1)
    waste_score: Optional[float] = Field(default=None, ge=0, le=1)


class RiskOutput(ApiModel):
    risk_score: float
    risk_level: str
    contributing: Dict[str, float] = Field(default_factory=dict)
    #: Stated exactly. It is an unweighted mean over the domains that reported — describing it as
    #: "weighted" would misrepresent the arithmetic to anyone reading the tool's own output.
    method: str = (
        "Unweighted mean of the domain scores that reported, banded by the core/risk.py "
        "thresholds (HIGH >= 0.70, MODERATE >= 0.40)"
    )
    note: str = (
        "Computed in Python by the same module the decision engine uses. A language model must "
        "never produce this number itself."
    )


def _calculate_environmental_risk(payload: RiskInput) -> RiskOutput:
    from core.risk import risk_level_for, round_half_up

    scores = {
        domain: value
        for domain, value in (
            ("air", payload.air_score),
            ("water", payload.water_score),
            ("waste", payload.waste_score),
        )
        if value is not None
    }
    if not scores:
        raise ToolError(
            "At least one domain score is required to calculate a risk.", code="INVALID_ARGUMENTS"
        )

    combined = round_half_up(sum(scores.values()) / len(scores))
    return RiskOutput(
        risk_score=combined,
        risk_level=risk_level_for(combined),
        contributing={domain: round_half_up(value) for domain, value in scores.items()},
    )


registry.register(Tool(
    name="calculate_environmental_risk",
    description=(
        "Combine per-domain risk scores into an overall risk score and band (LOW / MODERATE / "
        "HIGH) using the deterministic thresholds in core/risk.py. Call this instead of "
        "estimating a risk figure: the returned number is computed in Python and is the only "
        "figure with provenance. Domains that did not report are excluded rather than treated "
        "as zero, because missing data is not evidence of safety."
    ),
    input_model=RiskInput,
    output_model=RiskOutput,
    handler=_calculate_environmental_risk,
    category="decision",
))


# --------------------------------------------------------------------------- investigation


class InvestigationInput(LocationInput):
    pass


class InvestigationOutput(ApiModel):
    location: str
    risk_score: float
    risk_level: str
    sufficient_evidence: bool
    primary_problem: Optional[str] = None
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    data_gaps: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)


def _generate_investigation_plan(payload: InvestigationInput) -> InvestigationOutput:
    import asyncio

    from agents.langgraph_orchestrator import LangGraphOrchestrator

    orchestrator = LangGraphOrchestrator(demo_mode=payload.demo_mode)
    try:
        # The tool runs the real graph rather than a reduced copy of it: an investigation plan
        # built from different evidence than the dashboard shows would be worse than none.
        result = asyncio.run(orchestrator.analyze(payload.location, None))
    except RuntimeError as exc:
        raise ToolError(
            "generate_investigation_plan cannot run inside an active event loop; "
            "call it from a worker thread.",
            code="TOOL_FAILED",
        ) from exc

    decision = result.decision
    if decision is None:
        raise ToolError("The analysis produced no decision.", code="TOOL_FAILED")

    return InvestigationOutput(
        location=result.location,
        risk_score=decision.risk_score,
        risk_level=decision.risk_level,
        sufficient_evidence=decision.sufficient_evidence,
        primary_problem=decision.primary_problem.title if decision.primary_problem else None,
        actions=[a.model_dump(by_alias=True, mode="json") for a in decision.investigation_plan],
        data_gaps=list(decision.data_gaps),
        conflicts=[c.detail for c in decision.conflicts],
    )


registry.register(Tool(
    name="generate_investigation_plan",
    description=(
        "Run a full multi-agent analysis for a location and return what should be collected "
        "next: the prioritised investigation actions, the data gaps behind them, and any "
        "conflicts between measurements and observations. Use this when evidence is "
        "inconclusive and the question is 'what would settle it', rather than 'what is the "
        "answer'. Slower than the single-domain tools because it runs the whole graph."
    ),
    input_model=InvestigationInput,
    output_model=InvestigationOutput,
    handler=_generate_investigation_plan,
    category="decision",
    read_only=True,
))
