import io
from urllib.parse import parse_qs, urlparse

import pytest

from core.errors import GeocodingError, InvalidLocationError
from services.geocoding_service import NominatimClient, ReverseGeocodingService, parse_reverse

LAKE = {
    "display_name": "Bellandur Lake, Bellandur, Bengaluru, Karnataka, 560103, India",
    "category": "natural",
    "type": "water",
    "name": "Bellandur Lake",
    "address": {
        "water": "Bellandur Lake",
        "suburb": "Bellandur",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postcode": "560103",
        "country": "India",
    },
}
ROAD = {
    "display_name": "MG Road, Shivajinagar, Bengaluru, Karnataka, 560001, India",
    "category": "highway",
    "type": "primary",
    "name": "MG Road",
    "address": {"road": "MG Road", "suburb": "Shivajinagar", "city": "Bengaluru", "state": "Karnataka", "country": "India"},
}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def reverse(self, lat, lon):
        self.calls.append((lat, lon))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


def fast_service(client, **kwargs):
    return ReverseGeocodingService(client, min_interval_s=0, **kwargs)


def test_nominatim_success_parses_place_and_water_feature():
    place = parse_reverse(LAKE)
    assert place.city == "Bengaluru"
    assert place.state == "Karnataka"
    assert place.country == "India"
    assert place.neighbourhood == "Bellandur"
    assert place.postcode == "560103"
    assert place.water_feature == "Bellandur Lake"


def test_non_water_place_has_no_water_feature():
    assert parse_reverse(ROAD).water_feature is None


def test_nominatim_error_payload_is_unresolved():
    with pytest.raises(GeocodingError, match="place name could not be resolved"):
        parse_reverse({"error": "Unable to geocode"})


def test_nominatim_failure_is_reported_not_cached():
    client = FakeClient([GeocodingError("Location detected, but place name could not be resolved."), ROAD])
    service = fast_service(client)
    with pytest.raises(GeocodingError, match="place name could not be resolved"):
        service.reverse(12.9716, 77.5946)
    place, cached = service.reverse(12.9716, 77.5946)
    assert place.city == "Bengaluru" and cached is False
    assert len(client.calls) == 2


def test_cache_reused_for_small_movement():
    client = FakeClient([ROAD])
    service = fast_service(client, cache_distance_m=100)
    service.reverse(12.9716, 77.5946)
    place, cached = service.reverse(12.9717, 77.5947)  # ~15 m away
    assert cached is True and place.city == "Bengaluru"
    assert len(client.calls) == 1


def test_cache_bypassed_after_significant_movement():
    client = FakeClient([ROAD])
    service = fast_service(client, cache_distance_m=100)
    service.reverse(12.9716, 77.5946)
    _, cached = service.reverse(12.9800, 77.5946)  # ~930 m away
    assert cached is False
    assert len(client.calls) == 2


def test_requests_are_throttled_to_one_per_second():
    now = {"t": 100.0}
    sleeps = []
    client = FakeClient([ROAD])
    service = ReverseGeocodingService(
        client, min_interval_s=1.0, clock=lambda: now["t"], sleep=lambda s: sleeps.append(s)
    )
    service.reverse(12.9716, 77.5946)
    now["t"] += 0.25
    service.reverse(13.2, 77.8)  # far away -> new request
    assert sleeps and sleeps[0] == pytest.approx(0.75)


def test_invalid_coordinates_rejected():
    with pytest.raises(InvalidLocationError):
        fast_service(FakeClient([ROAD])).reverse(123.0, 77.0)


def test_client_sends_identifying_user_agent_and_only_coordinates():
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return Response(b'{"display_name": "Bengaluru, India", "address": {"city": "Bengaluru", "country": "India"}}')

    client = NominatimClient("https://nominatim.example", "EcoSentinel-AI/1.0 (test)", opener=opener)
    client.reverse(12.9716, 77.5946)

    url = urlparse(captured["url"])
    assert url.path == "/reverse"
    assert set(parse_qs(url.query)) == {"lat", "lon", "format"}
    assert parse_qs(url.query)["format"] == ["jsonv2"]
    assert captured["headers"]["User-agent"] == "EcoSentinel-AI/1.0 (test)"
