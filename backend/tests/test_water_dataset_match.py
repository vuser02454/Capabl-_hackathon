"""Reference-dataset appearance matching and citizen contamination reports.

The contract under test is mostly about restraint: an appearance match must never move a
sensor-backed risk score, never lose its reliability caveat, and never let a report claim it
reached an authority when nothing was transmitted.
"""

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.base import AgentTrace
from agents.water_agent import WaterAgentInput, WaterImage, WaterQualityAgent
from config import settings
from schemas import ContaminationReportRequest, LocationContext, WaterDatasetMatch
from services.location_service import resolve_location
from services.water_sensor_service import get_water_provider

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from services.water_dataset_match_service import (  # noqa: E402
    FEATURE_BINS,
    REGIONS,
    RELIABILITY_CAVEAT,
    DatasetMatcher,
    _features_and_hash,
    build_match_report,
    class_meta,
)
from services.report_service import build_summary, submit_report  # noqa: E402


@pytest.fixture
def override_settings():
    """`settings` is a frozen dataclass, so monkeypatch.setattr cannot touch it."""
    saved = {}

    def apply(**values):
        for name, value in values.items():
            saved.setdefault(name, getattr(settings, name))
            object.__setattr__(settings, name, value)

    yield apply
    for name, value in saved.items():
        object.__setattr__(settings, name, value)

def _image(color, size=(64, 64)) -> Image.Image:
    return Image.new("RGB", size, color)


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """A tiny two-class dataset: brown "Alta" frames and blue "Baja" frames."""
    for class_name, color in (("Alta", (120, 80, 40)), ("Baja", (40, 90, 160))):
        folder = tmp_path / class_name
        folder.mkdir()
        for index in range(4):
            shade = tuple(min(255, channel + index * 3) for channel in color)
            _image(shade).save(folder / f"S{index}-4_frame_{index:04d}.jpg", quality=95)
    return tmp_path


@pytest.fixture
def matcher(dataset: Path, tmp_path: Path) -> DatasetMatcher:
    instance = DatasetMatcher(dataset, tmp_path / "index.npz")
    instance.build()
    return instance


# ------------------------------------------------------------------ features


def test_feature_is_normalised_per_region():
    feature, digest = _features_and_hash(_image((100, 120, 140)))
    assert feature.shape == (FEATURE_BINS,)
    # Each of the spatial regions is an L1-normalised histogram, so the whole vector sums to REGIONS.
    assert feature.sum() == pytest.approx(REGIONS, abs=1e-3)
    assert 0 <= digest < 2**64


def test_identical_images_are_maximally_similar():
    a, _ = _features_and_hash(_image((90, 110, 130)))
    b, _ = _features_and_hash(_image((90, 110, 130)))
    assert float(np.minimum(a, b).sum() / REGIONS) == pytest.approx(1.0, abs=1e-6)


def test_unrelated_images_score_low():
    a, _ = _features_and_hash(_image((10, 10, 10)))
    b, _ = _features_and_hash(_image((240, 240, 240)))
    assert float(np.minimum(a, b).sum() / REGIONS) < 0.2


def test_class_meta_maps_spanish_labels_and_leaves_unknown_unmapped():
    assert class_meta("Alta") == ("High contamination", "HIGH")
    assert class_meta("baja")[1] == "LOW"
    label, level = class_meta("Sector7")
    assert label == "Sector7" and level is None


# ------------------------------------------------------------------ matching


def test_matches_its_own_class_and_flags_contamination(matcher):
    result = matcher.match(_encode(_image((120, 80, 40))))
    assert result.status == "ok"
    assert result.matched_class == "Alta"
    assert result.contaminated is True
    assert result.contamination_level == "HIGH"
    assert result.caveat == RELIABILITY_CAVEAT


def test_clean_class_match_does_not_raise_a_flag(matcher):
    result = matcher.match(_encode(_image((40, 90, 160))))
    assert result.status == "ok"
    assert result.matched_class == "Baja"
    assert result.contaminated is False


def test_unrelated_image_is_reported_as_no_match_not_as_clean(matcher):
    result = matcher.match(_encode(_image((255, 0, 255))))
    assert result.status == "no_match"
    assert result.contaminated is False
    assert result.matched_class is None
    # It must still carry the caveat: "no match" is not evidence the water is safe.
    assert result.caveat == RELIABILITY_CAVEAT
    assert "not being treated as evidence either way" in result.message


def test_near_duplicate_of_a_reference_frame_is_disclosed(matcher):
    result = matcher.match(_encode(_image((120, 80, 40))))
    assert result.near_duplicate is True
    assert result.duplicate_of and result.duplicate_of.startswith("Alta/")
    assert "replayed sample" in result.message


def test_unmapped_class_never_raises_a_flag(tmp_path: Path):
    folder = tmp_path / "Sector7"
    folder.mkdir()
    for index in range(3):
        _image((120, 80, 40)).save(folder / f"f{index}.jpg", quality=95)
    instance = DatasetMatcher(tmp_path, tmp_path / "index.npz")
    instance.build()
    result = instance.match(_encode(_image((120, 80, 40))))
    assert result.status == "ok"
    assert result.matched_class == "Sector7"
    assert result.contaminated is False
    assert result.contamination_level is None
    assert "not mapped to a contamination level" in result.message


def test_index_round_trips_through_its_cache(dataset: Path, tmp_path: Path):
    first = DatasetMatcher(dataset, tmp_path / "index.npz")
    first.build()
    second = DatasetMatcher(dataset, tmp_path / "index.npz")
    assert second.ensure_ready() is None  # loaded from cache, no rebuild
    assert second.describe()["datasetSize"] == first.describe()["datasetSize"]


def test_missing_dataset_reports_index_missing_without_raising(tmp_path: Path):
    instance = DatasetMatcher(tmp_path / "absent", tmp_path / "index.npz")
    with pytest.raises(Exception):
        instance.build()


def test_build_match_report_without_an_image_is_not_run():
    assert build_match_report(None).status == "not_run"


def test_build_match_report_survives_undecodable_bytes():
    result = build_match_report(b"definitely not an image")
    assert result.status in {"unavailable", "index_missing", "indexing", "not_run"}
    assert result.contaminated is False


# ------------------------------------------------------------------ agent integration


def test_dataset_match_never_moves_the_risk_score(monkeypatch):
    """The matcher misreads clean water often enough that it must stay out of the number."""
    location = resolve_location("Bengaluru", None)
    agent = WaterQualityAgent(get_water_provider(True))

    baseline = agent.run(location, AgentTrace())

    flagged = WaterDatasetMatch(
        status="ok",
        contaminated=True,
        matched_class="Alta",
        matched_label="High contamination",
        contamination_level="HIGH",
        similarity=0.99,
        caveat=RELIABILITY_CAVEAT,
    )
    monkeypatch.setattr("agents.water_agent.build_match_report", lambda _content: flagged)
    with_image = agent.run(
        WaterAgentInput(location=location, image=WaterImage(content=b"x", filename="w.jpg")),
        AgentTrace(),
    )

    assert with_image.dataset_match is not None
    assert with_image.dataset_match.contaminated is True
    assert with_image.risk_score == baseline.risk_score
    assert with_image.risk_level == baseline.risk_level


def test_no_image_means_no_dataset_match_block():
    location = resolve_location("Bengaluru", None)
    result = WaterQualityAgent(get_water_provider(True)).run(location, AgentTrace())
    assert result.dataset_match is None


# ------------------------------------------------------------------ reports


def _request(**overrides) -> ContaminationReportRequest:
    payload = dict(
        location=LocationContext(
            latitude=12.9716,
            longitude=77.5946,
            accuracy_m=10.0,
            display_name="Bellandur Lake, Bengaluru",
            city="Bengaluru",
        ),
        match=WaterDatasetMatch(
            status="ok",
            contaminated=True,
            matched_class="Alta",
            matched_label="High contamination",
            contamination_level="HIGH",
            similarity=0.97,
            vote_share=0.8,
            caveat=RELIABILITY_CAVEAT,
        ),
        observed_at=datetime.now(timezone.utc),
        source="camera",
    )
    payload.update(overrides)
    return ContaminationReportRequest(**payload)


def test_summary_carries_coordinates_and_the_reliability_caveat():
    summary = build_summary(_request(), "ECO-TEST-1")
    assert "12.97160, 77.59460" in summary
    assert "High contamination" in summary
    assert RELIABILITY_CAVEAT in summary
    assert "not a laboratory measurement" in summary


def test_report_without_a_destination_is_recorded_not_forwarded(tmp_path, override_settings):
    override_settings(reports_path=str(tmp_path), authority_webhook_url=None)

    receipt = submit_report(_request())

    assert receipt.status == "recorded"
    assert receipt.stored is True
    assert receipt.delivered_to is None
    assert "nothing was transmitted to any authority" in receipt.message
    logs = list(tmp_path.glob("contamination-*.jsonl"))
    assert len(logs) == 1
    record = json.loads(logs[0].read_text().strip())
    assert record["reference"] == receipt.reference
    assert record["location"]["latitude"] == pytest.approx(12.9716)


def test_failed_forward_is_never_reported_as_success(tmp_path, monkeypatch, override_settings):
    override_settings(reports_path=str(tmp_path), authority_webhook_url="https://example.invalid/hook")

    class _Boom:
        @staticmethod
        def post(*_args, **_kwargs):
            raise OSError("connection refused")

    monkeypatch.setitem(__import__("sys").modules, "httpx", _Boom)
    receipt = submit_report(_request())

    assert receipt.status == "forward_failed"
    assert receipt.stored is True
    assert "Send it yourself" in receipt.message


def test_successful_forward_names_only_the_host(tmp_path, monkeypatch, override_settings):
    override_settings(
        reports_path=str(tmp_path),
        authority_webhook_url="https://board.example.org/intake?token=secret",
    )

    class _Response:
        status_code = 202

    class _Ok:
        @staticmethod
        def post(*_args, **_kwargs):
            return _Response()

    monkeypatch.setitem(__import__("sys").modules, "httpx", _Ok)
    receipt = submit_report(_request())

    assert receipt.status == "forwarded"
    assert receipt.delivered_to == "board.example.org"
    assert "secret" not in receipt.message  # the token must never be echoed back


def test_photo_is_stored_beside_the_report(tmp_path, override_settings):
    import base64

    override_settings(reports_path=str(tmp_path), authority_webhook_url=None)

    encoded = base64.b64encode(_encode(_image((100, 100, 100)))).decode()
    receipt = submit_report(_request(photo=f"data:image/jpeg;base64,{encoded}"))

    photos = list((tmp_path / "photos").glob(f"{receipt.reference}.*"))
    assert len(photos) == 1
    assert photos[0].stat().st_size > 0


def test_malformed_photo_does_not_fail_the_report(tmp_path, override_settings):
    override_settings(reports_path=str(tmp_path), authority_webhook_url=None)

    receipt = submit_report(_request(photo="data:image/jpeg;base64,!!!not base64!!!"))

    assert receipt.stored is True
    assert not (tmp_path / "photos").exists()
