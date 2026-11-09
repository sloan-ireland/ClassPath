
import json
import os
import re
from pathlib import Path

import numpy as np
import requests

INDEX_PATH = Path(__file__).resolve().parent / "course_embeddings.json"

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",
).replace("/api/chat", "/api/embed")


class CourseRetriever:
    def __init__(self):
        with open(INDEX_PATH, "r", encoding="utf-8") as file:
            index = json.load(file)

        self.courses = index["courses"]
        self.embeddings = np.array(index["embeddings"], dtype=float)
        self.embedding_model = index["model"]

    def embed_query(self, query: str):
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": self.embedding_model,
                "input": query,
            },
            timeout=120,
        )
        response.raise_for_status()

        return np.array(
            response.json()["embeddings"][0],
            dtype=float,
        )

    def search(self, query: str, top_k: int = 3):
        # Prioritize exact course IDs when explicitly mentioned.
        matches = re.findall(
            r"\b([A-Za-z]{2,5})\s*-?\s*(\d{3,5})\b",
            query,
        )

        exact_results = []

        for subject, number in matches:
            if len(number) == 3:
                number += "00"

            course_id = f"{subject.upper()} {number}"

            for course in self.courses:
                if course["course_id"].upper() == course_id:
                    exact_results.append({
                        "course": course,
                        "score": 1.0,
                        "context": json.dumps(course),
                    })

        if exact_results:
            return exact_results[:top_k]

        # Generate an embedding for the student's question.
        query_embedding = self.embed_query(query)

        # Compute cosine similarity against all course embeddings.
        dot_products = self.embeddings @ query_embedding

        course_norms = np.linalg.norm(self.embeddings, axis=1)
        query_norm = np.linalg.norm(query_embedding)

        scores = dot_products / (
            course_norms * query_norm + 1e-10
        )

        # Rank courses from most similar to least similar.
        top_indices = np.argsort(scores)[::-1][:top_k]

        return [
            {
                "course": self.courses[i],
                "score": float(scores[i]),
                "context": json.dumps(self.courses[i]),
            }
            for i in top_indices
        ]


if __name__ == "__main__":
    retriever = CourseRetriever()

    results = retriever.search(
        "Which courses teach artificial intelligence?",
        top_k=5,
    )

    for result in results:
        course = result["course"]

        print(
            f"{course['course_id']} | "
            f"{course['title']} | "
            f"Similarity: {result['score']:.3f}"
        )
