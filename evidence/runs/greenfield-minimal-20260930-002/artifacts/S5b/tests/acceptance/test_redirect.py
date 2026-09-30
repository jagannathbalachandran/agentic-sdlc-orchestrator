# Traces: FR-2.AC1, FR-2.AC2
"""Acceptance tests for GET /{code} (FR-2), derived from
01-requirements.md acceptance criteria and 02-design.md DD-1/DD-4 contracts.
"""
from service.app import create_app


def make_client():
    app = create_app()
    return app.test_client()


def test_known_code_redirects_to_original_url():
    """FR-2.AC1: a code previously issued by POST /shorten redirects (3xx)
    with Location equal to the original long URL."""
    client = make_client()
    url = "https://example.com/some/long/path?q=1"
    shorten_response = client.post("/shorten", json={"url": url})
    code = shorten_response.get_json()["code"]

    response = client.get(f"/{code}", follow_redirects=False)

    assert 300 <= response.status_code < 400
    assert response.headers["Location"] == url


def test_unknown_code_returns_404_with_no_location_header():
    """FR-2.AC2: a code never issued by POST /shorten -> 404, no Location
    header set."""
    client = make_client()

    response = client.get("/this-code-was-never-issued", follow_redirects=False)

    assert response.status_code == 404
    assert "Location" not in response.headers
