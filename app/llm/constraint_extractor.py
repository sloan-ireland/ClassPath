
import json
import os

import requests
from pydantic import ValidationError

from app.schemas import PlanningRequest
from app.rag.course_resolver import CourseResolver


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
- Use the retrieved course records to identify full course IDs.
For example, CSCI 235 may correspond to CSCI 23500.
- The student's request determines which courses are required,
optional, or completed. Do not infer these categories solely
from retrieved records.
- Do not invent courses or prerequisites.
- Do not add prerequisite courses to the required list unless
the student explicitly requests them.
- Return only the PlanningRequest JSON object.
- Always include ALL fields from the required JSON structure.
- Never omit min_credits or max_credits.
- Extract credit limits from the STUDENT REQUEST, not course records.
- "12 to 16 credits" means min_credits = 12 and max_credits = 16.
- Course records are reference information only.
- Student requests take priority when extracting preferences.
- "term" represents the academic semester, such as "2026-fall".
- "prefs.earliest_start" represents the earliest acceptable
  class start time, NOT the semester.
- Convert "10 AM" to "10:00" and "2 PM" to "14:00".
- Never use "Fall", "Spring", or semester names as times.
- Extract scheduling preferences only from the student's request.
"""


def extract_constraints(student_prompt: str) -> PlanningRequest:
    # Retrieve course information relevant to the student's request.
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": student_prompt}
            ],
            "stream": False,
            "format": PlanningRequest.model_json_schema(),
            "options": {"temperature": 0},
        },
        timeout=120,
    )

    response.raise_for_status()

    content = response.json()["message"]["content"]
    print("Raw LLM output:")
    print(content)
    extracted_data = json.loads(content)

    try:
        planning_request = PlanningRequest.model_validate(extracted_data)

        resolver = CourseResolver()

        planning_request.required = [
            resolver.resolve(course)
            for course in planning_request.required
        ]

        planning_request.optional = [
            resolver.resolve(course)
            for course in planning_request.optional
        ]

        planning_request.completed = [
            resolver.resolve(course)
            for course in planning_request.completed
        ]

        return planning_request
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
