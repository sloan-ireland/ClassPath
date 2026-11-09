
from app.rag.course_loader import load_courses


class CourseResolver:
    def __init__(self):
        self.course_ids = {
            course["course_id"].upper()
            for course in load_courses()
        }

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
