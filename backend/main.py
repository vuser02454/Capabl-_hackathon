"""EcoSentinel AI — FastAPI entry point.

Run from the backend/ directory:
    uvicorn main:app --reload --port 8000

Privacy: endpoints that carry precise coordinates use POST bodies (never query strings),
so coordinates do not appear in access logs. Nothing here logs or stores them.
"""

import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from agents.base import AgentTrace
from agents.langgraph_orchestrator import LangGraphOrchestrator
from agents.orchestrator import AnalysisOrchestrator
from agents.registry import registry
from agents.waste_agent import UploadedImage
from agents.water_agent import WaterAgentInput, WaterImage, WaterQualityAgent
from config import settings
from core.errors import AnalysisFailedError, EcoSentinelError, ForbiddenError, InvalidLocationError, NotFoundError, UnauthorizedError
from data.history import RANGES, generate_history
from data.locations import get_location, list_locations, nearest_profile
from schemas import (
    WaterAgentResult,
    AgentsStatusResponse,
    AnalysisResult,
    AnalyzeRequest,
    ContaminationReportReceipt,
    ContaminationReportRequest,
    EnvironmentRequest,
    EnvironmentSnapshot,
    AiRoleStatus,
    AiStatusResponse,
    ChatCitation,
    ChatRequest,
    ChatResponse,
    ChatToolExecution,
    FrameScanVerdict,
    GeocodeResult,
    GeographicContext,
    GeographicContextRequest,
    KnowledgeRetrieval,
    KnowledgeSearchRequest,
    KnowledgeStatus,
    RetrievedKnowledge,
    ToolDescriptor,
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolListResponse,
    LocationContext,
    LocationInfo,
    MapStation,
    NearbyWaterBody,
    NearbyWaterRequest,
    NearbyWaterResponse,
    PlaceMatch,
    PlaceSearchRequest,
    PlaceSearchResponse,
    ReverseGeocodeRequest,
    WasteImageAnalysis,
    WastePipelineStatus,
    GeminiWasteResult,
    WasteSegregationResult,
    WaterBody,
    WaterDatasetMatch,
    WaterReadingIngest,
)
from services.geocoding_service import get_geocoder
from services.overpass_service import OverpassUnavailable, get_nearby_water_service
from services.report_service import submit_report
from services.location_service import context_from_profile, location_label, resolve_geographic_context, resolve_location
from services.openaq_service import resolve_air_provider_mode
from services.waste_detection_service import validate_image
from services.water_dataset_match_service import build_match_report, get_dataset_matcher
from services.water_sensor_service import get_water_provider
from services.water_sensor_service import WaterSourceRegistry, load_registry, reading_cache

from contextlib import asynccontextmanager  # noqa: E402
from safety import store as safety_store  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the schema, and seed the demo roster when the database is empty.

    Seeding on an EMPTY database only. A hosted free tier has an ephemeral filesystem, so without
    a persistent disk every deploy starts with nothing and the whole app renders blank — no
    workers, no reports, nothing to review. That is what this prevents.

    It is not a substitute for the disk: nothing typed into a demo survives the next deploy
    without one. It only ensures the app is never empty on arrival. On any database that already
    holds reports this is a no-op, so real data is never touched, and `seed_demo_data` is
    idempotent besides.

    A seeding failure must not stop the API serving — an empty demo is better than no service.
    """
    safety_store.init()
    try:
        if safety_store.count() == 0:
            from safety import people

            outcome = await run_in_threadpool(people.seed_demo_data)
            logging.getLogger("ecosentinel").info(
                "seeded_empty_database workers=%s reports=%s",
                outcome["users"]["workers"], outcome["reports"]["reports_created"])
    except Exception:  # noqa: BLE001
        logging.getLogger("ecosentinel").exception("startup_seed_failed")
    yield


app = FastAPI(
    title="EcoSentinel AI API",
    version="1.1.0",
    description="Multi-agent environmental monitoring and risk assessment.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- C3 Safety Intelligence -----------------------------------------------------------------
# Mounted as its own router. The environmental endpoints above are unchanged; this is additive.
from safety.api import router as safety_router  # noqa: E402
from safety.roles_api import admin_router, chat_router, worker_router  # noqa: E402

app.include_router(safety_router)
app.include_router(worker_router)
app.include_router(admin_router)
app.include_router(chat_router)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _live_providers() -> dict:
    """Providers used when the frontend calls the API with Demo Mode switched off."""
    try:
        return AnalysisOrchestrator(demo_mode=False).providers
    except EcoSentinelError as exc:
        return {"error": exc.message}


@app.exception_handler(EcoSentinelError)
async def handle_domain_error(_: Request, exc: EcoSentinelError) -> JSONResponse:
    return _error(exc.status_code, exc.code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Wrap HTTPException into the same envelope every other error uses.

    Without this, FastAPI emits {"detail": ...} while the frontend reads {"error": {"message": ...}},
    so a handler's carefully worded message ("Map data is unavailable right now.") reached the user
    as a generic HTTP-status string. The code is derived from the status so the client can branch.
    """
    codes = {400: "BAD_REQUEST", 404: "NOT_FOUND", 413: "PAYLOAD_TOO_LARGE",
             415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR", 503: "SERVICE_UNAVAILABLE"}
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _error(exc.status_code, codes.get(exc.status_code, "REQUEST_FAILED"), detail)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "request"
    return _error(422, "VALIDATION_ERROR", f"Invalid {field}: {first.get('msg', 'bad input')}")


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    return _error(500, "INTERNAL_ERROR", "Something went wrong while processing the request.")


# --------------------------------------------------------------------------- system


@app.get("/health")
def platform_health() -> dict:
    """Liveness probe for the hosting platform (Render).

    Deliberately trivial and unversioned: a health check that touches the database or an LLM
    reports the platform unhealthy when a dependency is degraded, and the platform responds by
    restarting a process that was serving fine. `/api/health` is the rich one.
    """
    return {"status": "ok", "service": "EcoSentinel Safety Intelligence"}


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "EcoSentinel AI",
        "version": app.version,
        "demoMode": settings.default_demo_mode,
        "providers": _live_providers(),
        "airProviderMode": resolve_air_provider_mode(),
        "geocoding": "OpenStreetMap Nominatim (server-side, cached)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/agents/status", response_model=AgentsStatusResponse)
def agents_status() -> AgentsStatusResponse:
    agents = registry.snapshot(_live_providers())
    operational = all(agent.status == "operational" for agent in agents)
    return AgentsStatusResponse(
        operational=operational,
        summary="All agents operational" if operational else "One or more agents degraded",
        agents=agents,
    )


# --------------------------------------------------------------------------- location


@app.get("/api/locations")
def locations() -> dict:
    return {"locations": [{"id": l["id"], "name": l["name"], "region": l["region"]} for l in list_locations()]}


@app.post("/api/location/reverse", response_model=GeocodeResult)
def reverse_geocode(request: ReverseGeocodeRequest) -> GeocodeResult:
    """Coordinates -> place name via Nominatim (geographic context only)."""
    place, cached = get_geocoder().reverse(request.latitude, request.longitude)
    return GeocodeResult(**place.as_dict(), cached=cached)


@app.post("/api/location/search", response_model=PlaceSearchResponse)
def search_places(request: PlaceSearchRequest) -> PlaceSearchResponse:
    """Free-text place name -> coordinates, via Nominatim forward geocoding.

    Lets any place be analysed, not only the presets in shared/locations.json. Water features are
    flagged with `isWater` so a UI can surface lakes and rivers ahead of generic addresses.

    Restricted to India by default (`country_codes="in"`). The restriction is applied as
    Nominatim's own filter AND re-checked against each result's structured `country_code`, so a
    result is kept because its address says India, not because the query mentioned it.
    """
    matches, cached = get_geocoder().search(
        request.query, request.limit, request.country_codes)
    return PlaceSearchResponse(
        query=request.query,
        matches=[PlaceMatch(**match.as_dict()) for match in matches],
        cached=cached,
        countryCodes=request.country_codes or None,
    )


@app.post("/api/water/nearby-bodies", response_model=NearbyWaterResponse)
async def nearby_water_bodies(request: NearbyWaterRequest) -> NearbyWaterResponse:
    """Named water bodies near a point, from OpenStreetMap via Overpass.

    GEOGRAPHIC CONTEXT ONLY: this returns names, types and distances. Overpass holds no
    water-quality data, so nothing here influences a measurement or a risk score — it answers
    "which lake is this?", which is what a contamination report needs in order to be actionable.

    Never fails the caller: an unreachable or rate-limited Overpass returns `status: "unavailable"`
    with an empty list, so the UI can say "couldn't identify the water body" instead of breaking.
    """
    if not settings.overpass_enabled:
        return NearbyWaterResponse(
            status="disabled", message="Nearby water body lookup is switched off on this backend."
        )

    service = get_nearby_water_service()
    try:
        features, nearest, cached = await run_in_threadpool(
            service.nearby, request.latitude, request.longitude, request.radius_m, request.limit
        )
    except OverpassUnavailable as exc:
        return NearbyWaterResponse(status="unavailable", message=exc.message)

    bodies = [NearbyWaterBody(**feature.as_dict()) for feature in features]
    # Taken from the full result set, not from `bodies`, which the caller's limit has truncated.
    named = NearbyWaterBody(**nearest.as_dict()) if nearest else None
    return NearbyWaterResponse(
        status="ok",
        bodies=bodies,
        nearest_named=named,
        radius_m=request.radius_m or settings.overpass_radius_m,
        cached=cached,
        message=None if bodies else "No mapped water body was found within the search radius.",
    )


@app.get("/api/ai/status", response_model=AiStatusResponse)
def ai_status() -> AiStatusResponse:
    """Which AI roles are configured, and whether they can answer.

    The two roles are reported separately because they are not interchangeable: Gemini performs
    functional AI work whose output becomes evidence, while OpenRouter/Groq only put an
    already-final decision into words.

    Never returns an API key, a fragment of one, or anything from which one could be derived —
    only whether a key is present.
    """
    from services import rag
    from services.ai import explainability, functional
    from services.water_vision_service import status as vision_status

    return AiStatusResponse(
        functional_ai=AiRoleStatus(**functional.status()),
        explainable_ai=AiRoleStatus(**explainability.status()),
        vision=AiRoleStatus(**vision_status()),
        # Retrieval is reported as its own capability: it supplies grounding passages and holds
        # no opinion, so folding it into explainability would misdescribe both.
        knowledge=KnowledgeStatus(**rag.status()),
    )


@app.get("/api/tools", response_model=ToolListResponse)
def list_tools() -> ToolListResponse:
    """Every registered tool with its JSON Schema.

    The schemas are the OpenAI/Anthropic function-calling shape, so this endpoint is what a model
    would be handed to route over. It is also what the UI renders, which keeps the advertised
    tool surface and the callable one identical by construction.
    """
    from services import tools as tool_layer

    descriptors = [
        ToolDescriptor(
            name=tool.name,
            description=tool.description,
            category=tool.category,
            read_only=tool.read_only,
            parameters=tool.input_model.model_json_schema(),
        )
        for tool in tool_layer.list_tools()
    ]
    return ToolListResponse(tools=descriptors, count=len(descriptors))


@app.post("/api/tools/{name}/invoke", response_model=ToolInvokeResponse)
async def invoke_tool(name: str, request: ToolInvokeRequest) -> ToolInvokeResponse:
    """Run one tool by name.

    Always returns 200 with a structured result, including for failures: a caller running several
    tools needs to see which ones failed and why, not a transport error that loses the detail.
    Arguments are validated against the tool's own input model before anything runs.
    """
    from services import tools as tool_layer

    result = await run_in_threadpool(tool_layer.invoke, name, request.arguments)
    return ToolInvokeResponse(
        tool=result.tool,
        ok=result.ok,
        duration_ms=result.duration_ms,
        output=result.output,
        error=result.error,
        error_code=result.error_code,
    )


@app.post("/api/knowledge/search", response_model=KnowledgeRetrieval)
def search_knowledge_endpoint(request: KnowledgeSearchRequest) -> KnowledgeRetrieval:
    """Free-text search over the knowledge corpus.

    The same retriever the analysis pipeline uses, exposed directly so the UI can show what is
    retrievable and a reader can check any citation. Results below the relevance floor are not
    returned: a retriever that always answers will cite something for a question the corpus
    cannot address, which is the failure this pipeline exists to avoid.
    """
    from services import rag

    results = rag.search_knowledge(request.query, top_k=request.top_k, domain=request.domain)
    store_status = rag.status()
    return KnowledgeRetrieval(
        status="ok" if store_status.get("available") else "unavailable",
        query=request.query,
        embedding=store_status.get("embedding", "tfidf-sparse-lexical"),
        documents_indexed=store_status.get("documents", 0),
        chunks_indexed=store_status.get("chunks", 0),
        min_score=store_status.get("min_score"),
        message=None if results else "No corpus passage cleared the relevance floor for this query.",
        results=[
            RetrievedKnowledge(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_title=r.document_title,
                section=r.section,
                domain=r.domain,
                source_file=r.source,
                content=r.text,
                score=min(1.0, max(0.0, r.score)),
                domain_matched=r.domain_matched,
                used_by="Knowledge search",
            )
            for r in results
        ],
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Answer a question about one specific analysis.

    Every answer is grounded in that analysis's decision state. `analysisId` is required and an
    unknown one is refused rather than answered from the most recent analysis — explaining one
    river with another river's evidence reads perfectly and is entirely wrong.

    Works with no LLM configured: the deterministic answer is always available, and an
    explainability provider only rephrases it.
    """
    from services.ai import chat_agent
    from services.ai.chat import store as decision_store

    outcome = await run_in_threadpool(chat_agent.respond, request.analysis_id, request.question)

    # An `analysis` intent with no held analysis is the one case worth a 404: the user is asking
    # about something specific that this backend does not have, and answering from another
    # analysis would read perfectly and be entirely wrong. Functional and general intents need no
    # analysis at all, so they are served normally.
    if outcome.intent == "analysis" and decision_store.get(request.analysis_id) is None:
        raise NotFoundError(
            "That analysis is no longer available to ask about. Run the analysis again, then ask."
        )

    return ChatResponse(
        analysis_id=request.analysis_id,
        question=request.question,
        answer=outcome.answer,
        evidence_ids=outcome.evidence_ids,
        source=outcome.source,
        llm_enhanced=outcome.llm_enhanced,
        intent=outcome.intent,  # type: ignore[arg-type]
        tool_executions=[
            ChatToolExecution(
                tool=execution.tool,
                purpose=execution.purpose,
                status=execution.status,  # type: ignore[arg-type]
                duration_ms=execution.duration_ms,
                summary=execution.summary,
                error=execution.error,
            )
            for execution in outcome.tool_executions
        ],
        citations=[
            ChatCitation(
                chunk_id=c.get("chunkId") or "",
                document_title=c.get("documentTitle") or "",
                section=c.get("section") or "",
                source_file=c.get("sourceFile"),
                score=float(c.get("score") or 0.0),
                content=c.get("content") or "",
            )
            for c in outcome.citations
            if c.get("chunkId")
        ],
    )


@app.post("/api/location/context", response_model=GeographicContext)
async def geographic_context(request: GeographicContextRequest) -> GeographicContext:
    """Contextual OpenStreetMap features near a point, from Overpass.

    CONTEXT ONLY. This reports what contributors have MAPPED — industrial land, waste facilities,
    waterways and major roads. A mapped factory is a drawn polygon, not an emission and not
    evidence that anything is polluting: nothing here is a measurement, and nothing here feeds a
    risk score. Describe it as "industrial activity is mapped near this location", never as a cause.

    Never fails the caller: an unreachable, disabled or rate-limited Overpass returns
    `available: false` with a reason, so the UI can say why instead of breaking.
    """
    return await run_in_threadpool(
        resolve_geographic_context,
        request.latitude,
        request.longitude,
        request.radius_m,
        request.per_category,
    )


def _snapshot(context: LocationContext) -> EnvironmentSnapshot:
    profile, _ = nearest_profile(context.latitude, context.longitude)
    return EnvironmentSnapshot(
        location=LocationInfo(
            id=profile["id"],
            name=location_label(context),
            region=context.state or profile["region"],
            lat=context.latitude,
            lon=context.longitude,
        ),
        stations=[MapStation(**station) for station in profile["map"]["stations"]],
        water_bodies=[WaterBody(**body) for body in profile["map"]["waterBodies"]],
        history={key: generate_history(profile, key) for key in RANGES},
    )


@app.get("/api/environment/{location}", response_model=EnvironmentSnapshot)
def environment(location: str) -> EnvironmentSnapshot:
    return _snapshot(context_from_profile(get_location(location)))


@app.post("/api/environment", response_model=EnvironmentSnapshot)
def environment_for_context(request: EnvironmentRequest) -> EnvironmentSnapshot:
    return _snapshot(resolve_location(None, request.location_context))


# --------------------------------------------------------------------------- analysis


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze(request: AnalyzeRequest) -> AnalysisResult:
    """Runs the full agent pipeline through the LangGraph StateGraph orchestrator by default
    (agents/langgraph_orchestrator.py): location resolution, then the air/water/waste
    specialists in parallel, then the Coordinator. Set ECOSENTINEL_LANGGRAPH_ORCHESTRATION=false
    to fall back to the original sequential AnalysisOrchestrator (agents/orchestrator.py) — the
    response schema (AnalysisResult) is identical either way.
    """
    if settings.langgraph_orchestration_enabled:
        return await LangGraphOrchestrator(request.demo_mode).analyze(request.location, request.location_context)
    context = resolve_location(request.location, request.location_context)
    return await run_in_threadpool(AnalysisOrchestrator(request.demo_mode).analyze, context)


@app.post("/api/analyze/graph", response_model=AnalysisResult)
async def analyze_graph(request: AnalyzeRequest) -> AnalysisResult:
    """Development/testing endpoint: always runs the LangGraph orchestrator, regardless of the
    ECOSENTINEL_LANGGRAPH_ORCHESTRATION toggle, so the graph path can be exercised directly.
    """
    return await LangGraphOrchestrator(request.demo_mode).analyze(request.location, request.location_context)


@app.post("/api/waste/analyze", response_model=WasteImageAnalysis)
async def analyze_waste(
    location: Optional[str] = Form(None),
    location_context: Optional[str] = Form(None),
    demo_mode: bool = Form(True),
    reassess: bool = Form(True),
    file: Optional[UploadFile] = File(None),
) -> WasteImageAnalysis:
    parsed_context = None
    if location_context:
        try:
            parsed_context = LocationContext.model_validate_json(location_context)
        except ValidationError:
            raise InvalidLocationError("Location context is invalid.")
    context = resolve_location(location or (None if parsed_context else "Bengaluru"), parsed_context)

    image = None
    if file is not None:
        content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)
        image = UploadedImage(content=content, filename=file.filename or "upload.jpg")
    orchestrator = AnalysisOrchestrator(demo_mode)
    return await run_in_threadpool(orchestrator.analyze_waste_image, context, image, reassess)


@app.post("/api/water/analyze-image", response_model=WaterAgentResult)
async def analyze_water_image(
    location: Optional[str] = Form(None),
    location_context: Optional[str] = Form(None),
    demo_mode: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    investigate: bool = Form(False),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    accuracy_meters: Optional[float] = Form(None),
    location_source: Optional[str] = Form(None),
) -> WaterAgentResult:
    """Water Agent run with an optional water image for YOLO26 visual pollution detection.

    The water-quality half of the report (pH / turbidity / temperature / TDS) is produced by the
    same provider chain as every other Water Agent run; the image only adds the `visualPollution`
    block. With no image, or with the model unconfigured, this returns a normal Water Agent
    report and says so in `visualPollution.status` — it never fails the analysis.

    `investigate=true` additionally builds the clicked-frame explainable-AI report (WHERE / WHY /
    WHAT NEXT) into `investigation`. The optional latitude/longitude/accuracy are provenance for
    that frame: recorded and displayed, never fed into a score, and never inferred. A caller that
    omits them — because the user denied location — still gets the full visual investigation, with
    `geotag.available = false` and a reason.

    This extends the existing endpoint rather than adding a second one, so there is a single
    image-analysis path to keep correct.
    """
    parsed_context = None
    if location_context:
        try:
            parsed_context = LocationContext.model_validate_json(location_context)
        except ValidationError:
            raise InvalidLocationError("Location context is invalid.")
    context = resolve_location(location or (None if parsed_context else "Bengaluru"), parsed_context)

    image = None
    if file is not None:
        content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)
        image = WaterImage(content=content, filename=file.filename or "water.jpg")

    from schemas import InvestigationGeotag

    if not investigate:
        agent = WaterQualityAgent(get_water_provider(demo_mode))
        trace = AgentTrace()
        return await run_in_threadpool(agent.run, WaterAgentInput(location=context, image=image), trace)

    if latitude is not None and longitude is not None:
        geotag = InvestigationGeotag(
            available=True, latitude=latitude, longitude=longitude,
            accuracy_meters=accuracy_meters, captured_at=datetime.now(timezone.utc),
            source=location_source if location_source in ("browser", "manual", "preset") else None,
        )
        # Reuse the cached Nominatim path the rest of the app uses. A missing name never
        # invalidates the geotag — the coordinates are the provenance, the label is a convenience.
        try:
            place, _cached = await run_in_threadpool(get_geocoder().reverse, latitude, longitude)
            geotag = geotag.model_copy(update={"resolved_name": place.display_name or place.city})
        except EcoSentinelError:
            pass
    else:
        geotag = InvestigationGeotag(
            available=False,
            message="Location unavailable - investigation can continue without geotagging.",
        )

    # The investigation runs through the SAME LangGraph workflow as every other analysis: the
    # frame enters the water specialist, its detections become evidence, and the identical
    # normalize -> detect -> cross-signal -> conflicts -> sufficiency -> synthesis path runs over
    # them. There is no second decision engine.
    analysis = await LangGraphOrchestrator(demo_mode=demo_mode).investigate_frame(
        location_name=None, location_context=context, image=image, geotag=geotag
    )
    if analysis.water is not None:
        return analysis.water

    # No sensor or dataset covers this location. The visual investigation is still valid, so it is
    # returned in a report whose measurements are explicitly absent rather than failing the
    # request — and rather than inventing readings to fill the shape of a water report.
    if analysis.investigation is None:
        raise AnalysisFailedError(
            "Neither water measurements nor a visual investigation could be produced for this frame."
        )
    return _vision_only_water_result(context, analysis)


def _vision_only_water_result(context: LocationContext, analysis: AnalysisResult) -> WaterAgentResult:
    """A water report carrying a visual investigation and NO measurements.

    Every measurement field is null and `sensorStatus` is "offline", because that is the truth:
    no sensor or dataset covered this location. `dataAvailability` on the investigation states it
    outright, so a reader cannot mistake an absent reading for a normal one. No risk is asserted
    from an image — the score stays 0 and the warnings say why.
    """
    investigation = analysis.investigation
    assert investigation is not None
    return WaterAgentResult(
        location=location_label(context),
        risk_level="LOW",
        risk_score=0.0,
        # No measurements means no confidence in a water-quality assessment, visual evidence or not.
        confidence=0.0,
        timestamp=datetime.now(timezone.utc),
        data_source="Visual investigation only",
        is_mock=False,
        measurements=[],
        findings=[],
        warnings=[
            "No water sensor or dataset covers this location, so no water-quality measurements "
            "accompany this frame.",
            "The risk score is not derived from the image: visible pollution cannot establish "
            "chemical or microbiological contamination.",
        ],
        sensor_id="none",
        sensor_name="No water source available",
        sensor_status="offline",
        ph=None,
        turbidity=None,
        temperature=None,
        source_type="demo",
        visual_pollution=analysis.water.visual_pollution if analysis.water else None,
        investigation=investigation,
    )


@app.get("/api/waste/pipeline-status", response_model=WastePipelineStatus)
def waste_pipeline_status() -> WastePipelineStatus:
    """Which stages of the two-stage waste pipeline are available."""
    from services.waste.waste_pipeline import pipeline_status

    status = pipeline_status()
    classifier = status["classifier"]
    return WastePipelineStatus(
        detector=AiRoleStatus(**status["detector"]),
        classifier_configured=bool(classifier.get("configured")),
        classifier_available=bool(classifier.get("available")),
        classifier_classes=classifier.get("classes") or [],
        classification_threshold=classifier.get("threshold"),
        detail=classifier.get("detail"),
    )


@app.post("/api/waste/segregate", response_model=WasteSegregationResult)
async def segregate_waste(
    file: UploadFile = File(...),
    explain: bool = Query(
        False,
        description=(
            "Add a Grad-CAM attribution per classified crop. Off by default: it costs a backward "
            "pass per object and explains a decision that has already been made."
        ),
    ),
) -> WasteSegregationResult:
    """Two-stage waste analysis: detect objects, crop each one, classify the waste type.

    The detector's class and the classifier's class are reported separately. When the detector
    already emits a waste-taxonomy class (TACO `waste_detector.pt`), that class is the
    segregation label. A COCO detector still needs the classifier, because `bottle` / `cup`
    are not waste classes.

    With `?explain=true` each classified crop also carries `xai`: a Grad-CAM heatmap computed from
    the classifier's own gradients. Where it cannot be computed the field says so rather than
    carrying a substitute image.
    """
    content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)

    from services.waste.waste_pipeline import analyze_waste

    result = await run_in_threadpool(
        analyze_waste, content, file.filename or "image.jpg", None, None, None, explain
    )
    return WasteSegregationResult.model_validate(result)


@app.post("/api/waste/gemini-detect", response_model=GeminiWasteResult)
async def gemini_detect_waste(
    file: UploadFile = File(...),
    save_candidate: bool = Query(
        False,
        description=(
            "Stage the image and Gemini's annotations under datasets/waste_user_candidates/pending "
            "for human review. Off by default: an unreviewed pseudo-label is not training data."
        ),
    ),
) -> GeminiWasteResult:
    """EXPERIMENTAL second opinion from Gemini, for comparison against the production detector.

    This is NOT the production path and never calls YOLO. `POST /api/waste/segregate` is
    unchanged and still runs `waste_detector.pt`; Gemini is not consulted when that endpoint is
    uncertain. Whether it ever should be is a decision for the numbers this endpoint collects.

    `confidence` is always null. Gemini returns a label and a box, not a calibrated probability,
    and a fabricated score would be compared against YOLO's real one.
    """
    content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)

    from services.waste import gemini_detect as gemini

    result = await run_in_threadpool(gemini.detect, content, file.filename or "image.jpg")

    if save_candidate and not result.get("error"):
        result["candidate"] = await run_in_threadpool(
            gemini.save_candidate, content, file.filename or "image.jpg", result
        )

    return GeminiWasteResult.model_validate(result)


@app.post("/api/waste/debug")
async def debug_waste(file: UploadFile = File(...)) -> dict:
    """DIAGNOSTIC ONLY. Every intermediate stage of one waste analysis, for one image.

    Temporary. It exists to locate which stage is producing wrong labels — detection, cropping,
    preprocessing, classification or taxonomy mapping — none of which can be told apart from a
    final label alone.

    It observes `analyze_waste` rather than re-running its own version of it, so what is reported
    is what production does. The response is deliberately untyped: it carries raw model internals
    (full probability vectors, the de-normalised network input) that have no place in the API
    contract and should not acquire one.

    Artefacts are also written to `runs/debug_waste/`.
    """
    content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)

    from services.waste.waste_debug import camelize, debug_analyze

    manifest = await run_in_threadpool(debug_analyze, content, file.filename or "image.jpg")
    return camelize(manifest)


@app.post("/api/water/scan-frame", response_model=FrameScanVerdict)
async def scan_frame(file: UploadFile = File(...)) -> FrameScanVerdict:
    """The live camera's only question: is there visible contamination in this frame?

    Runs the same YOLO detector as a full investigation but returns just a verdict. While a camera
    is streaming, a full explanation per frame would be expensive, would narrate footage nobody
    chose, and would train people to ignore the alert. The detailed work happens once, on a frame
    the user deliberately picks.

    `contaminated` is true only for POLLUTION-relevant classes. A general-purpose model seeing a
    person by the water is not a contamination finding, so those are counted separately.
    """
    content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)

    from core.investigation import is_pollution_class
    from services.water_vision_service import build_report, get_water_vision_detector

    report = await run_in_threadpool(
        build_report, get_water_vision_detector(), content, file.filename or "frame.jpg"
    )
    if report.status != "ok":
        return FrameScanVerdict(status=report.status, model=report.model, message=report.message)

    pollution = [d for d in report.detections if is_pollution_class(d.class_name)]
    other = [d for d in report.detections if d not in pollution]
    return FrameScanVerdict(
        status="ok",
        contaminated=bool(pollution),
        object_count=len(pollution),
        other_object_count=len(other),
        classes=sorted({d.class_name for d in pollution}),
        model=report.model,
        message=None
        if pollution
        else "No supported visible pollution objects in this frame.",
    )


@app.post("/api/water/match-frame", response_model=WaterDatasetMatch)
async def match_water_frame(file: UploadFile = File(...)) -> WaterDatasetMatch:
    """Appearance-match a single frame against the labelled reference dataset — nothing else.

    This is the fast path the live camera polls: no sensor lookup, no risk scoring, no storage.
    A `contaminated` result means the frame RESEMBLES reference frames labelled contaminated; the
    `caveat` field carries the measured reliability of that claim and callers must show it.
    """
    content = validate_image(await file.read(), file.content_type, settings.max_upload_bytes)
    return await run_in_threadpool(build_match_report, content)


@app.get("/api/water/dataset-status")
async def water_dataset_status() -> dict:
    """Reference-index health: whether it is built, how big it is, and its match thresholds."""
    matcher = get_dataset_matcher()
    await run_in_threadpool(matcher.ensure_ready)
    return matcher.describe()


# --------------------------------------------------------------------------- citizen reports


@app.post("/api/reports/contamination", response_model=ContaminationReportReceipt)
async def report_contamination(request: ContaminationReportRequest) -> ContaminationReportReceipt:
    """Record a citizen contamination report, and forward it only if a destination is configured.

    PRIVACY: unlike the rest of this API, this endpoint PERSISTS the precise coordinates in the
    request body, because a report without a location is useless. The frontend only calls it after
    an explicit per-report confirmation showing exactly what will be stored. The receipt never
    claims an authority received anything unless a configured destination actually accepted it.
    """
    return await run_in_threadpool(submit_report, request)


# --------------------------------------------------------------------------- sensor ingest


@app.post("/api/sensors/water/{sensor_id}/readings")
def ingest_water_reading(
    sensor_id: str,
    reading: WaterReadingIngest,
    x_sensor_token: Optional[str] = Header(None),
) -> dict:
    """Push endpoint for ESP32 boards or an MQTT bridge (provider "mqtt" in the registry)."""
    if not settings.sensor_ingest_token:
        raise ForbiddenError("Sensor ingestion is disabled. Set ECOSENTINEL_SENSOR_INGEST_TOKEN to enable it.")
    if not hmac.compare_digest(x_sensor_token or "", settings.sensor_ingest_token):
        raise UnauthorizedError("Invalid sensor token.")
    source = WaterSourceRegistry(load_registry(settings.water_registry_path)).find(sensor_id)
    if source is None or source.provider != "mqtt" or not source.enabled:
        raise NotFoundError(f"Sensor '{sensor_id}' is not registered for pushed readings.")

    payload = reading.model_dump(exclude_none=True)
    payload["observed_at"] = (reading.observed_at or datetime.now(timezone.utc)).isoformat()
    reading_cache.ingest(sensor_id, payload)
    return {"status": "accepted", "sensorId": sensor_id}
