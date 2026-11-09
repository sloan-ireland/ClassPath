
import json
import os
from pathlib import Path

import requests

from app.rag.course_loader import load_courses


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",
).replace("/api/chat", "/api/embed")

EMBEDDING_MODEL = "nomic-embed-text"

INDEX_PATH = Path(__file__).resolve().parent / "course_embeddings.json"


def course_to_document(course: dict) -> str:
    """Convert a course into text useful for semantic search."""

    return (
        f"Course ID: {course['course_id']}\n"
        f"Title: {course.get('title') or 'Unknown'}\n"
        f"Term: {course['term_id']}\n"
        f"Prerequisites: {course.get('prerequisites') or 'None'}\n"
        f"Corequisites: {course.get('corequisites') or 'None'}"
    )


def build_embedding_index():
    courses = load_courses()

    if not courses:
        raise ValueError("No courses returned from Supabase.")

    documents = [
        course_to_document(course)
        for course in courses
    ]

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": EMBEDDING_MODEL,
            "input": documents,
        },
        timeout=300,
    )
    response.raise_for_status()

    embeddings = response.json()["embeddings"]

    if len(embeddings) != len(courses):
        raise ValueError("Embedding count does not match course count.")

    index = {
        "model": EMBEDDING_MODEL,
        "courses": courses,
        "embeddings": embeddings,
    }

    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Indexed {len(courses)} courses.")
    print(f"Embedding dimensions: {len(embeddings[0])}")
    print(f"Saved index to: {INDEX_PATH}")


if __name__ == "__main__":
    build_embedding_index()
