
import json
from pathlib import Path


# Locate the course_data folder from the project root.
COURSE_DATA_DIR = Path(__file__).resolve().parents[2] / "course_data"


def load_courses() -> list[dict]:
    courses = []

    # Read all six course dataset files.
    for file_path in sorted(COURSE_DATA_DIR.glob("*.json")):
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        # Support datasets containing either a list of courses
        # or an object with a "courses" list.
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("courses", [])
        else:
            raise ValueError(f"Unexpected JSON structure: {file_path}")

        for course in records:
            if not isinstance(course, dict):
                raise ValueError(f"Invalid course record: {file_path}")

            courses.append(course)

    return courses


if __name__ == "__main__":
    courses = load_courses()

    print(f"Loaded {len(courses)} courses")

    for course in courses[:5]:
        print(course.get("course_id"))
