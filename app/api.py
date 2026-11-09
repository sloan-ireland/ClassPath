
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.schemas import PlanningRequest
from app.llm.constraint_extractor import extract_constraints


app = FastAPI(
    title="ClassPath API",
    description="AI-powered course scheduling assistant",
    version="0.1.0",
)


class ScheduleRequest(BaseModel):
    message: str = Field(min_length=1)


class ScheduleResponse(BaseModel):
    status: str
    constraints: PlanningRequest
    schedules: list = Field(default_factory=list)


@app.post("/schedule", response_model=ScheduleResponse)
def generate_schedule(request: ScheduleRequest):
    try:
        # Step 1: Extract scheduling constraints using Qwen.
        constraints = extract_constraints(request.message)

        # Step 2: Retrieve relevant course information.
        # TODO: Integrate embedding-based retrieval where needed.

        # Step 3: Generate valid schedules using Ada's CSP solver.
        # TODO: Integrate CSP.

        # Step 4: Rank schedules using Sloan's RL model.
        # TODO: Integrate RL.

        return ScheduleResponse(
            status="constraints_extracted",
            constraints=constraints,
            schedules=[],
        )

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
