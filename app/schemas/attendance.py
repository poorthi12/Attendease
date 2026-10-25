from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AttendanceSubmission(BaseModel):
    class_date: date
    statuses: dict[str, Literal["present", "absent"]] = Field(min_length=1, max_length=500)

    @field_validator("class_date")
    @classmethod
    def date_not_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Attendance date cannot be in the future.")
        return value
