
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class SchedulingPreferences(BaseModel):
    earliest_start: str | None = None
    avoid_days: list[str] = Field(default_factory=list)

    @field_validator("earliest_start")
    @classmethod
    def validate_start_time(cls, value):
        if value is not None:
            datetime.strptime(value, "%H:%M")
        return value

    @field_validator("avoid_days")
    @classmethod
    def validate_days(cls, days):
        valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}

        for day in days:
            if day not in valid_days:
                raise ValueError(f"Invalid day: {day}")

        return days


class PlanningRequest(BaseModel):
    # Semester being planned
    term: str

    # Courses the student must take
    required: list[str] = Field(default_factory=list)

    # Courses the student would like to take
    optional: list[str] = Field(default_factory=list)

    # Courses the student has already completed
    completed: list[str] = Field(default_factory=list)

    # Acceptable credit range
    min_credits: int = Field(ge=0)
    max_credits: int = Field(ge=0)

    # Scheduling preferences
    prefs: SchedulingPreferences = Field(
        default_factory=SchedulingPreferences
    )

    @model_validator(mode="after")
    def validate_credit_range(self):
        if self.min_credits > self.max_credits:
            raise ValueError(
                "min_credits cannot exceed max_credits"
            )

        return self
