
import os

from dotenv import load_dotenv
from supabase import create_client


load_dotenv()


def load_courses() -> list[dict]:
    client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )

    courses = []
    page_size = 500
    offset = 0

    # Supabase may limit how many rows one request returns,
    # so retrieve courses in batches.
    while True:
        response = (
            client.table("courses")
            .select("*")
            .order("term_id")
            .order("course_id")
            .range(offset, offset + page_size - 1)
            .execute()
        )

        batch = response.data
        for course in batch:
            course["term"] = course["term_id"]
            courses.append(course)

        if len(batch) < page_size:
            break

        offset += page_size

    print(f"Loaded {len(courses)} courses from Supabase.")

    return courses


if __name__ == "__main__":
    courses = load_courses()

    for course in courses[:5]:
        print(
            course["course_id"],
            course["title"],
            course["term_id"],
        )
