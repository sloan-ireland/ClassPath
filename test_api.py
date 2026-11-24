"""End-to-end tests for /schedule that need neither Ollama nor Supabase.

The LLM step (extract_constraints) is replaced with a function returning a
hand-written PlanningRequest, so these tests exercise the API -> CSP path.
"""

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.schemas import PlanningRequest
from app.rag.course_resolver import CourseResolver


def fake_extractor(request_dict):
    return lambda message: PlanningRequest.model_validate(request_dict)


@pytest.fixture
def client():
    return TestClient(api.app)


def test_schedule_returns_top3_from_csp(client, monkeypatch):
    monkeypatch.setattr(api, "extract_constraints", fake_extractor({
        "term": "2026-fall",
        "required": ["CSCI 23500", "CSCI 26000", "MATH 15500"],
        "optional": ["CSCI 26500", "STAT 21300"],
        "completed": ["CSCI 12700", "CSCI 13500", "CSCI 15000",
                      "CSCI 16000", "MATH 15000"],
        "min_credits": 12, "max_credits": 16,
        "prefs": {"earliest_start": "10:00", "avoid_days": ["Fri"]},
    }))
    res = client.post("/schedule", json={"message": "anything"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "scheduled"
    assert 1 <= len(body["schedules"]) <= 3
    scores = [s["score"] for s in body["schedules"]]
    assert scores == sorted(scores)
    for s in body["schedules"]:
        assert 12 <= s["credits"] <= 16
        courses = {e["course"] for e in s["sections"]}
        assert {"CSCI 23500", "CSCI 26000", "MATH 15500"} <= courses
        # avoid_days preference: no Friday meetings expected in this case
        assert not any("Fri" in t for e in s["sections"] for t in e["times"])


def test_missing_prereq_gives_no_schedule_with_reason(client, monkeypatch):
    monkeypatch.setattr(api, "extract_constraints", fake_extractor({
        "term": "2026-fall", "required": ["CSCI 33500"], "completed": [],
        "min_credits": 0, "max_credits": 18,
    }))
    body = client.post("/schedule", json={"message": "x"}).json()
    assert body["status"] == "no_valid_schedule"
    assert body["schedules"] == []
    assert "CSCI 33500" in body["report"]["blocked"]


def test_unknown_term_is_422(client, monkeypatch):
    monkeypatch.setattr(api, "extract_constraints", fake_extractor({
        "term": "2030-fall", "required": ["CSCI 23500"],
        "min_credits": 0, "max_credits": 18,
    }))
    res = client.post("/schedule", json={"message": "x"})
    assert res.status_code == 422
    assert "2030-fall" in res.json()["detail"]


def test_resolver_falls_back_to_json_when_supabase_down(monkeypatch):
    def broken_loader():
        raise RuntimeError("project paused")
    monkeypatch.setattr("app.rag.course_resolver.load_courses", broken_loader)
    resolver = CourseResolver()
    assert resolver.resolve("csci 235") == "CSCI 23500"
    assert resolver.resolve("MATH 155") == "MATH 15500"
