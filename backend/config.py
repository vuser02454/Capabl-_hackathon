"""Runtime configuration, driven by environment variables (and backend/.env if present)."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent
SHARED_DIR = REPO_DIR / "shared"

try:  # python-dotenv ships with uvicorn[standard]; it is optional
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
except ImportError:  # pragma: no cover
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Air: "auto" uses OpenAQ when OPENAQ_API_KEY is set, otherwise demo data. Options: auto | openaq | mock.
    air_provider: str = os.getenv("ECOSENTINEL_AIR_PROVIDER", "auto")
    # Water: "auto" resolves the nearest registered sensor/station/dataset. "mock" always uses demo data.
    water_provider: str = os.getenv("ECOSENTINEL_WATER_PROVIDER", "auto")
    waste_provider: str = os.getenv("ECOSENTINEL_WASTE_PROVIDER", "mock")

    openaq_api_key: Optional[str] = os.getenv("OPENAQ_API_KEY") or None
    openaq_base_url: str = os.getenv("OPENAQ_BASE_URL", "https://api.openaq.org/v3")
    openaq_radius_m: int = int(os.getenv("ECOSENTINEL_OPENAQ_RADIUS_M", "25000"))
    openaq_max_age_hours: float = float(os.getenv("ECOSENTINEL_OPENAQ_MAX_AGE_HOURS", "24"))
    # Missing pollutants may use older "latest available" readings up to this age (labelled as delayed).
    openaq_fill_max_age_hours: float = float(os.getenv("ECOSENTINEL_OPENAQ_FILL_MAX_AGE_HOURS", "96"))
    openaq_timeout_seconds: float = float(os.getenv("ECOSENTINEL_OPENAQ_TIMEOUT", "6"))

    # Reverse geocoding (geographic context only) — OpenStreetMap Nominatim.
    nominatim_base_url: str = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
    nominatim_user_agent: str = os.getenv(
        "ECOSENTINEL_NOMINATIM_USER_AGENT", "EcoSentinel-AI/1.0 (environmental monitoring hackathon project)"
    )
    nominatim_email: Optional[str] = os.getenv("NOMINATIM_EMAIL") or None
    geocode_cache_distance_m: float = float(os.getenv("ECOSENTINEL_GEOCODE_CACHE_DISTANCE_M", "100"))

    # --- Nearby water bodies via the OpenStreetMap Overpass API (services/overpass_service.py) ---
    # GEOGRAPHIC CONTEXT ONLY: Overpass supplies names, types and positions of water features.
    # It carries no water-quality data and never contributes to a risk score.
    # Overpass is donated infrastructure with no API key — the client throttles, caches and caps
    # every query. Point ECOSENTINEL_OVERPASS_BASE_URL at your own instance for heavy use.
    overpass_enabled: bool = _env_bool("ECOSENTINEL_OVERPASS_ENABLED", True)
    overpass_base_url: str = os.getenv("ECOSENTINEL_OVERPASS_BASE_URL", "https://overpass-api.de/api/interpreter")
    overpass_radius_m: int = int(os.getenv("ECOSENTINEL_OVERPASS_RADIUS_M", "1500"))
    overpass_max_radius_m: int = int(os.getenv("ECOSENTINEL_OVERPASS_MAX_RADIUS_M", "5000"))
    overpass_max_results: int = int(os.getenv("ECOSENTINEL_OVERPASS_MAX_RESULTS", "12"))
    # Sent to Overpass as [timeout:N] so the server drops a runaway query too.
    overpass_timeout_seconds: float = float(os.getenv("ECOSENTINEL_OVERPASS_TIMEOUT_SECONDS", "25"))
    overpass_cache_distance_m: float = float(os.getenv("ECOSENTINEL_OVERPASS_CACHE_DISTANCE_M", "250"))
    # Hard ceiling on the LangGraph geographic-enrichment node. Overpass is a free shared service
    # that can stall for far longer than its own [timeout:] suggests, and the Coordinator fan-in
    # waits on this node — so without a bound here, a slow Overpass stalls the whole analysis.
    # Must stay comfortably below the frontend's 30 s analysis timeout (services/apiClient.ts).
    overpass_context_timeout_seconds: float = float(os.getenv("ECOSENTINEL_OVERPASS_CONTEXT_TIMEOUT", "10"))

    # Water source resolution.
    water_registry_path: str = os.getenv("ECOSENTINEL_WATER_REGISTRY_PATH", str(SHARED_DIR / "water_sensors.json"))
    water_dataset_path: Optional[str] = os.getenv("ECOSENTINEL_WATER_DATASET_PATH") or None
    water_sensor_radius_km: float = float(os.getenv("ECOSENTINEL_WATER_SENSOR_RADIUS_KM", "10"))
    water_dataset_radius_km: float = float(os.getenv("ECOSENTINEL_WATER_DATASET_RADIUS_KM", "25"))
    water_max_age_minutes: float = float(os.getenv("ECOSENTINEL_WATER_MAX_AGE_MINUTES", "60"))
    sensor_ingest_token: Optional[str] = os.getenv("ECOSENTINEL_SENSOR_INGEST_TOKEN") or None

    firebase_db_url: Optional[str] = os.getenv("FIREBASE_DB_URL") or None
    firebase_auth_token: Optional[str] = os.getenv("FIREBASE_AUTH_TOKEN") or None
    mqtt_broker_url: Optional[str] = os.getenv("MQTT_BROKER_URL")
    yolo_weights_path: str = os.getenv("YOLO_WEIGHTS_PATH", "models/waste-yolov8n.pt")
    # Waste pipeline detector (POST /api/waste/segregate). Separate from YOLO26_MODEL_PATH so the
    # Water Agent can keep a general COCO model while waste uses TACO-trained weights.
    waste_detector_model_path: Optional[str] = os.getenv("WASTE_DETECTOR_MODEL_PATH", "models/waste_detector.pt") or None

    # --- Water Pollution Vision (YOLO26 Nano) ---
    # Visual detection of floating//shoreline pollution in water imagery. It is a SEPARATE signal
    # from the water-quality parameters (pH / turbidity / temperature / TDS), which come from
    # sensors and datasets — a vision model cannot measure them.
    # provider: auto (default) | local | roboflow | off
    #   auto     -> local weights when YOLO26_MODEL_PATH exists, else Roboflow when configured, else unavailable
    #   local    -> Ultralytics-compatible weights at YOLO26_MODEL_PATH
    #   roboflow -> Roboflow hosted inference (ROBOFLOW_API_KEY + ROBOFLOW_MODEL_ID)
    #   off      -> never run vision
    water_vision_provider: str = os.getenv("ECOSENTINEL_WATER_VISION_PROVIDER", "auto").strip().lower()
    yolo26_model_path: Optional[str] = os.getenv("YOLO26_MODEL_PATH") or None
    yolo_confidence_threshold: float = float(os.getenv("YOLO_CONFIDENCE_THRESHOLD", "0.25"))
    roboflow_api_key: Optional[str] = os.getenv("ROBOFLOW_API_KEY") or None
    roboflow_model_id: Optional[str] = os.getenv("ROBOFLOW_MODEL_ID") or None
    roboflow_base_url: str = os.getenv("ROBOFLOW_BASE_URL", "https://detect.roboflow.com")
    roboflow_timeout_seconds: float = float(os.getenv("ROBOFLOW_TIMEOUT_SECONDS", "12"))
    # Share of the combined water risk contributed by the visual signal, when vision actually ran.
    # 0 keeps the existing water-quality-only score untouched; see agents/water_agent.py for how
    # the two signals are blended and why this default was chosen.
    water_visual_weight: float = float(os.getenv("ECOSENTINEL_WATER_VISUAL_WEIGHT", "0.25"))
    # Object count in one frame treated as maximum visual pollution density when normalising.
    water_visual_count_reference: float = float(os.getenv("ECOSENTINEL_WATER_VISUAL_COUNT_REFERENCE", "20"))

    # --- Reference-dataset appearance matching (services/water_dataset_match_service.py) ---
    # Compares an uploaded water photo against a folder of labelled reference frames laid out as
    # <images path>/<ClassName>/*.jpg. This is an APPEARANCE match (colour histograms), not a
    # measurement: it can corroborate that water looks contaminated, never that it is chemically
    # safe. Needs pillow + numpy.
    water_dataset_matching_enabled: bool = _env_bool("ECOSENTINEL_WATER_DATASET_MATCHING", True)
    water_dataset_images_path: str = os.getenv(
        "ECOSENTINEL_WATER_DATASET_IMAGES_PATH", str(REPO_DIR / "datasets")
    )
    water_dataset_index_path: str = os.getenv(
        "ECOSENTINEL_WATER_DATASET_INDEX_PATH", str(BACKEND_DIR / "data" / "water_dataset_index.npz")
    )
    # Minimum histogram-intersection similarity (0..1) before a match counts at all. Below this the
    # report says "no confident match" and flags nothing. Calibrated in scripts/calibrate_dataset_match.py.
    water_dataset_match_threshold: float = float(os.getenv("ECOSENTINEL_WATER_DATASET_MATCH_THRESHOLD", "0.62"))
    # Max 64-bit dHash Hamming distance for "this is the same frame the dataset already has".
    water_dataset_duplicate_max_distance: int = int(
        os.getenv("ECOSENTINEL_WATER_DATASET_DUPLICATE_DISTANCE", "6")
    )
    water_dataset_top_k: int = int(os.getenv("ECOSENTINEL_WATER_DATASET_TOP_K", "5"))
    # Matched contamination levels that raise the contaminated flag.
    water_dataset_flag_levels: frozenset = field(
        default_factory=lambda: frozenset(
            part.strip().upper()
            for part in os.getenv("ECOSENTINEL_WATER_DATASET_FLAG_LEVELS", "HIGH,MODERATE").split(",")
            if part.strip()
        )
    )

    # --- Citizen contamination reports (services/report_service.py) ---
    # Reports are always written to this backend's own log. They are additionally forwarded ONLY
    # when a destination is configured here; with no destination the API says plainly that nothing
    # was transmitted, and never implies an authority received anything.
    reports_path: str = os.getenv("ECOSENTINEL_REPORTS_PATH", str(BACKEND_DIR / "data" / "reports"))
    authority_webhook_url: Optional[str] = os.getenv("ECOSENTINEL_AUTHORITY_WEBHOOK_URL") or None
    authority_webhook_token: Optional[str] = os.getenv("ECOSENTINEL_AUTHORITY_WEBHOOK_TOKEN") or None
    authority_name: str = os.getenv("ECOSENTINEL_AUTHORITY_NAME", "the configured pollution-control destination")
    authority_timeout_seconds: float = float(os.getenv("ECOSENTINEL_AUTHORITY_TIMEOUT_SECONDS", "10"))

    agent_timeout_seconds: float = float(os.getenv("ECOSENTINEL_AGENT_TIMEOUT", "15"))
    max_upload_bytes: int = int(os.getenv("ECOSENTINEL_MAX_UPLOAD_MB", "25")) * 1024 * 1024
    default_demo_mode: bool = _env_bool("ECOSENTINEL_DEMO_MODE", True)
    cors_origins: List[str] = field(
        default_factory=lambda: os.getenv("ECOSENTINEL_CORS_ORIGINS", "*").split(",")
    )

    # --- LangGraph orchestration ---
    # /api/analyze runs through the LangGraph StateGraph orchestrator by default. Setting this to
    # false falls back to the original ThreadPoolExecutor-based AnalysisOrchestrator (agents/orchestrator.py).
    langgraph_orchestration_enabled: bool = _env_bool("ECOSENTINEL_LANGGRAPH_ORCHESTRATION", True)

    # --- AI provider roles -------------------------------------------------------------------
    # Two LLM roles, deliberately NOT interchangeable. Giving them one shared setting is how a
    # model that is supposed to explain a finished decision ends up making one.
    #
    #   FUNCTIONAL  (Gemini)            performs AI work inside the pipeline — interpreting an
    #                                   image, extracting structure. Its output is validated
    #                                   against a Pydantic schema and enters as EVIDENCE, where
    #                                   the deterministic engine weighs it like any other signal.
    #
    #   EXPLAINABILITY (OpenRouter/Groq) receives an ALREADY-FINAL decision and puts it into
    #                                   words. It cannot reach the score, confidence, priority,
    #                                   evidence or primary problem — see services/ai/explainability.py.
    #
    # Neither role is required: with both set to "none" the whole pipeline still runs and every
    # explanation falls back to the deterministic text.
    functional_ai_provider: str = os.getenv("FUNCTIONAL_AI_PROVIDER", "none").strip().lower()
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    explainability_ai_provider: str = os.getenv("EXPLAINABILITY_AI_PROVIDER", "none").strip().lower()
    openrouter_api_key: Optional[str] = os.getenv("OPENROUTER_API_KEY") or None
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    groq_api_key: Optional[str] = os.getenv("GROQ_API_KEY") or None
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    # --- Coordinator LLM narrative (legacy, optional) ---
    # The Coordinator's risk score and structured findings are ALWAYS computed deterministically
    # (agents/coordinator_agent.py, backend/core/risk.py) — an LLM never sets a number. When configured,
    # an LLM only adds an extra natural-language narrative on top of that deterministic result.
    # provider: none (default) | gemini | openai | groq
    llm_provider: str = os.getenv("LLM_PROVIDER", "none").strip().lower()
    llm_model: str = os.getenv("LLM_MODEL", "")
    # Falls back to the provider's own conventional env var (GOOGLE_API_KEY / OPENAI_API_KEY / GROQ_API_KEY)
    # via the LangChain client itself when LLM_API_KEY is not set.
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY") or None
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))


settings = Settings()
