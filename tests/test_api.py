"""HTTP-level tests through FastAPI's TestClient."""

from __future__ import annotations


def test_health_reports_the_data_source(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["data_source"] == "fixture"


def test_config_never_leaks_secrets(client):
    body = client.get("/api/config").json()
    assert body["geo_source"] == "fixture"
    assert body["llm_source"] == "rule-based-offline"
    assert body["speech_available"] is False
    assert "api_key" not in str(body).lower()
    assert "token" not in str(body).lower()


def test_config_lists_languages_and_sample_places(client):
    body = client.get("/api/config").json()
    assert "hi-IN" in body["languages"]
    assert "Sekuru" in body["sample_places"]


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Bhoomi Mitra" in response.text


def test_openapi_schema_is_published(client):
    schema = client.get("/openapi.json").json()
    assert "/api/assistant/ask" in schema["paths"]
    assert "/api/village/report" in schema["paths"]


# -- village report -------------------------------------------------------


def test_village_report_by_name(client):
    response = client.post(
        "/api/village/report", json={"place": "Sekuru", "radius_m": 20000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["village"]["population"] == 10207
    assert body["land_cover"]["classes"]
    assert body["facilities"]
    assert body["data_source"] == "fixture"


def test_village_report_by_coordinates(client):
    response = client.post(
        "/api/village/report", json={"lat": 16.2794, "lon": 80.5884, "radius_m": 20000}
    )
    assert response.status_code == 200
    assert response.json()["village"]["name"] == "Sekuru"


def test_village_report_rejects_missing_location(client):
    response = client.post("/api/village/report", json={"radius_m": 5000})
    assert response.status_code == 422


def test_village_report_rejects_bad_latitude(client):
    response = client.post("/api/village/report", json={"lat": 999, "lon": 0})
    assert response.status_code == 422


def test_village_report_unknown_place_is_404(client):
    response = client.post("/api/village/report", json={"place": "Atlantis"})
    assert response.status_code == 404
    assert response.json()["error"] == "place_not_found"


def test_village_report_can_disable_routes(client):
    body = client.post(
        "/api/village/report",
        json={"place": "Sekuru", "radius_m": 20000, "include_routes": False},
    ).json()
    assert body["routes"] == []


# -- assistant ------------------------------------------------------------


def test_assistant_answers_a_question(client):
    response = client.post(
        "/api/assistant/ask",
        json={"question": "Tell me about Sekuru", "language_code": "en-IN"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["tool_trace"]
    assert body["data_source"] == "fixture"


def test_assistant_reports_its_tool_trace(client):
    body = client.post(
        "/api/assistant/ask", json={"question": "Tell me about Sekuru"}
    ).json()
    names = [t["name"] for t in body["tool_trace"]]
    assert names[0] == "resolve_place"


def test_assistant_rejects_an_empty_question(client):
    response = client.post("/api/assistant/ask", json={"question": ""})
    assert response.status_code == 422


def test_assistant_rejects_an_over_long_question(client):
    response = client.post("/api/assistant/ask", json={"question": "x" * 1001})
    assert response.status_code == 422


def test_voice_endpoint_is_503_without_a_sarvam_key(client):
    response = client.post(
        "/api/assistant/voice",
        files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")},
        data={"language_code": "en-IN"},
    )
    assert response.status_code == 503
    assert "SARVAM_API_KEY" in response.json()["detail"]


# -- error mapping --------------------------------------------------------


def test_upstream_auth_failure_maps_to_502(client, container):
    from bhoomi.domain.errors import UpstreamAuthError

    class Exploding:
        def resolve(self, place):
            raise UpstreamAuthError("bad token")

        def reverse(self, point):
            raise UpstreamAuthError("bad token")

    container.report._places = Exploding()  # type: ignore[attr-defined]
    response = client.post("/api/village/report", json={"place": "Sekuru"})
    assert response.status_code == 502
    assert response.json()["error"] == "upstream_auth_failed"


def test_upstream_outage_maps_to_503(client, container):
    from bhoomi.domain.errors import UpstreamUnavailableError

    class Exploding:
        def resolve(self, place):
            raise UpstreamUnavailableError("down")

        def reverse(self, point):
            raise UpstreamUnavailableError("down")

    container.report._places = Exploding()  # type: ignore[attr-defined]
    response = client.post("/api/village/report", json={"place": "Sekuru"})
    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"


# -- map layers -----------------------------------------------------------


def test_map_layers_endpoint_lists_bases_and_overlays(client):
    body = client.get("/api/map/layers").json()
    assert [b["id"] for b in body["base_layers"]] == ["satellite", "plain"]
    assert len(body["overlays"]) == 20
    assert body["default_overlay_id"] == body["overlays"][-1]["id"]


def test_map_layers_point_at_the_isro_wms(client):
    body = client.get("/api/map/layers").json()
    overlay = body["overlays"][0]
    assert overlay["layer_name"].startswith("LULC250K_")
    assert overlay["service_url"].startswith("https://")
    assert "Bhuvan" in overlay["attribution"]


def test_map_layers_expose_no_secrets(client):
    body = client.get("/api/map/layers").text.lower()
    assert "api_key" not in body
    assert "bhuvan_token" not in body


def test_map_layers_year_labels_are_human_readable(client):
    years = [o["year"] for o in client.get("/api/map/layers").json()["overlays"]]
    assert "2015-16" in years
    assert "2024-25" in years
