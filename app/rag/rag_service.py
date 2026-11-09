
import os
import requests

from app.rag.retriever import CourseRetriever


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat"
)

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:4b")


class RAGService:
    def __init__(self):
        # Load and index the course dataset.
        self.retriever = CourseRetriever()

    def answer(self, question: str, term: str | None = None) -> str:
        # Retrieve relevant course records.
        results = self.retriever.search(question, top_k=6)

        # Filter results by semester if specified.
        if term:
            results = [
                result for result in results
                if result["course"].get("term") == term
            ]

        if not results:
            return "I couldn't find relevant course information in the dataset."

        # Combine the retrieved course records into context.
        context = "\n\n".join(
            result["context"]
            for result in results
        )

        # Tell Qwen to answer using the retrieved information.
        system_prompt = """
You are ClassPath, a university course planning assistant.

Answer student questions using ONLY the provided course data.

Rules:
- Do not invent courses, prerequisites, or restrictions.
- If a prerequisite has an "all" field, all listed courses are required.
- If a prerequisite has an "any" field, at least one listed course is required.
- Explain course requirements clearly and concisely.
- If information is missing, say that it is unavailable.
- Do not claim a student is eligible unless their requirements
  have been verified.
- Do not treat missing prerequisite data as proof that
  a course has no prerequisites.
"""

        user_prompt = f"""
Course data:
{context}

Student question:
{question}
"""

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0
                },
            },
            timeout=120,
        )

        response.raise_for_status()

        content = response.json()["message"]["content"]

        # remove any qwen reasoning text that appears before </think>.
        if "</think>" in content:
            content = content.split("</think>", 1)[1]

        return content.strip()


if __name__ == "__main__":
    rag = RAGService()

    question = "What are the prerequisites for CSCI 499?"

    print("Question:", question)
    print()
    print("ClassPath:", rag.answer(question, term="2026-fall"))
