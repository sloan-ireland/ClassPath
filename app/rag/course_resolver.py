import json
from pathlib import Path

from app.rag.course_loader import load_courses

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "course_data"


def _load_course_ids_from_json() -> set[str]:
    """Course IDs from the local course_data/*.json files."""
    ids = set()
    for path in DATA_DIR.glob("*.json"):
        data = json.loads(path.read_text())
        ids.update(c["course_id"].upper() for c in data["courses"])
    return ids


class CourseResolver:
    def __init__(self):
        try:
            self.course_ids = {
                course["course_id"].upper()
                for course in load_courses()
            }
        except Exception as error:
            # Supabase unavailable (paused project, missing .env, no network).
            # The JSON files hold the same course IDs, so fall back to them.
            print(f"Supabase unavailable ({error}); using course_data/*.json")
            self.course_ids = _load_course_ids_from_json()

    def resolve(self, course_id: str) -> str:
        course_id = " ".join(course_id.upper().split())

        # Exact match.
        if course_id in self.course_ids:
            return course_id

        # Expand common abbreviated Hunter course IDs.
        parts = course_id.split()

        if len(parts) == 2:
            subject, number = parts

            if len(number) == 3 and number.isdigit():
                full_id = f"{subject} {number}00"

                if full_id in self.course_ids:
                    return full_id

        # Preserve unmatched IDs instead of inventing a course.
        return course_id
