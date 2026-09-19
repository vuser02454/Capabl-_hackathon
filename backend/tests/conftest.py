"""Test setup: external services are never contacted.

Environment is fixed BEFORE application modules are imported, so the real
OpenAQ key in backend/.env is ignored and Nominatim points at an unroutable address.
"""

import os
import sys
from pathlib import Path

os.environ["OPENAQ_API_KEY"] = ""
os.environ["NOMINATIM_BASE_URL"] = "http://127.0.0.1:9"
os.environ["ECOSENTINEL_SENSOR_INGEST_TOKEN"] = "test-token"
os.environ["ECOSENTINEL_WATER_PROVIDER"] = "auto"
os.environ["ECOSENTINEL_WATER_DATASET_PATH"] = ""
os.environ["FIREBASE_DB_URL"] = ""
# Overpass is donated infrastructure: the suite must never call it. Tests that exercise the
# client inject a stub instead (tests/test_overpass_service.py).
os.environ["ECOSENTINEL_OVERPASS_ENABLED"] = "false"
os.environ["ECOSENTINEL_OVERPASS_BASE_URL"] = "http://127.0.0.1:9/api/interpreter"

# Both AI roles OFF for the whole suite. Real keys in backend/.env would otherwise be picked up by
# load_dotenv and the tests would call Gemini, Groq and OpenRouter for real — spending the
# operator's quota, and making results depend on a third party's uptime. Tests that exercise a
# provider inject a stub (tests/test_ai_providers.py).
os.environ["FUNCTIONAL_AI_PROVIDER"] = "none"
os.environ["EXPLAINABILITY_AI_PROVIDER"] = "none"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
# Vision off for the suite. backend/.env may now point at real YOLO weights, and loading torch
# per test would make the suite slow and its results dependent on a model file. Tests that need
# detections construct a WaterVisionReport directly (tests/test_frame_investigation.py).
# "local" with no weights, which is what the suite has always exercised: the detector exists and
# reports model_not_configured. "off" would return not_run instead and change the contract under
# test. Either way torch is never loaded, so the suite stays fast and independent of a model file.
os.environ["ECOSENTINEL_WATER_VISION_PROVIDER"] = "local"
os.environ["YOLO26_MODEL_PATH"] = ""
# Waste detector off for the suite for the same reason: backend/models/waste_detector.pt exists
# on disk, and loading it would pull torch into every test that constructs the pipeline.
os.environ["WASTE_DETECTOR_MODEL_PATH"] = ""

os.environ["LLM_PROVIDER"] = "none"
os.environ["LLM_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from schemas import LocationContext  # noqa: E402


@pytest.fixture
def bengaluru_gps() -> LocationContext:
    return LocationContext(
        latitude=12.9716,
        longitude=77.5946,
        accuracy_m=18,
        display_name="Bengaluru, Karnataka, India",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        source="browser_geolocation",
        geocoding="nominatim",
    )


@pytest.fixture(autouse=True)
def _clear_pushed_readings():
    from services.water_sensor_service import reading_cache

    reading_cache.clear()
    yield
    reading_cache.clear()
