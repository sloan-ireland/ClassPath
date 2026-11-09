
import json
import os

import requests
from pydantic import ValidationError

from app.schemas import PlanningRequest


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat"
)

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:4b")


SYSTEM_PROMPT = """
You extract university course scheduling constraints from student requests.

Return only a JSON object matching this structure:
{
  "term": "2026-fall",
  "required": [],
  "optional": [],
  "completed": [],
  "min_credits": 12,
  "max_credits": 16,
  "prefs": {
    "earliest_start": null,
    "avoid_days": []
  }
}

Rules:
- Use course IDs such as "CSCI 23500".
- Required courses are courses the student explicitly needs.
- Optional courses are courses the student would like to take.
- Completed courses are courses the student says they finished.
- Use day abbreviations: Mon, Tue, Wed, Thu, Fri, Sat, Sun.
- Use 24-hour time in HH:MM format.
- Never invent completed courses or scheduling preferences.
- If the term or credit limits are missing, use null.
- Do not include explanations or Markdown.
"""


def extract_constraints(student_prompt: str) -> PlanningRequest:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": student_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        timeout=120,
    )

    response.raise_for_status()

    content = response.json()["message"]["content"]
    extracted_data = json.loads(content)

    try:
        return PlanningRequest.model_validate(extracted_data)
    except ValidationError as error:
        raise ValueError(
            f"LLM produced invalid scheduling constraints: {error}"
        ) from error


if __name__ == "__main__":
    prompt = (
        "For Fall 2026, I need CSCI 235 and CSCI 260. "
        "I've already completed CSCI 135 and CSCI 150. "
        "I want 12 to 16 credits, no Fridays, "
        "and no classes before 10 AM."
    )

    result = extract_constraints(prompt)
    print(result.model_dump_json(indent=2))
