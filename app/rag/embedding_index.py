
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


def build_embedding_index():
    courses = load_courses()

    # Convert each course into searchable text.
    documents = [
        json.dumps(course, ensure_ascii=False)
        for course in courses
    ]

    # Ask the embedding model to convert the text into vectors.
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

    # Save the course records and their embeddings together.
    index = {
        "model": EMBEDDING_MODEL,
        "courses": courses,
        "embeddings": embeddings,
    }

    INDEX_PATH.write_text(
        json.dumps(index),
        encoding="utf-8",
    )

    print(f"Indexed {len(courses)} courses.")
    print(f"Embedding dimensions: {len(embeddings[0])}")
    print(f"Saved index to: {INDEX_PATH}")


if __name__ == "__main__":
    build_embedding_index()
