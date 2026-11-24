"""Step 3 of /schedule: turn a PlanningRequest (from the LLM step) into
ranked schedules using the CSP + heuristic search solver.

Course data comes from course_data/*.json for now. Those files keep the
structured all/any prerequisites and the section types (lecture/recitation)
the solver needs. Swap `get_courses` for a Supabase loader once the database
has the same fields.
"""

from functools import lru_cache
from pathlib import Path

from app.schemas import PlanningRequest
from csp_solver import load_courses, solve

DATA_DIR = Path(__file__).resolve().parent.parent / "course_data"


@lru_cache(maxsize=None)
def get_courses(term: str) -> dict:
    """Load one term's courses once and reuse them across requests."""
    return load_courses(term, data_dir=str(DATA_DIR))


def available_terms() -> set[str]:
    import json
    return {json.loads(p.read_text())["term"] for p in DATA_DIR.glob("*.json")}


def build_schedules(request: PlanningRequest, top_k: int = 3) -> dict:
    """Run the CSP solver on an extracted PlanningRequest.

    Returns {"schedules": [...], "report": {...}} where report explains
    blocked courses (missing prereqs, not offered) and unverified prereqs.
    """
    if request.term not in available_terms():
        raise ValueError(
            f"No course data for term '{request.term}'. "
            f"Available: {sorted(available_terms())}"
        )

    # Only pass preferences the student actually stated; the solver's
    # DEFAULT_PREFS fill in everything else.
    prefs = {k: v for k, v in request.prefs.model_dump().items()
             if v not in (None, [])}

    schedules, report = solve(
        get_courses(request.term),
        required=request.required,
        optional=request.optional,
        completed=request.completed,
        min_credits=request.min_credits,
        max_credits=request.max_credits,
        prefs=prefs,
        top_k=top_k,
    )
    return {"schedules": schedules, "report": report}
