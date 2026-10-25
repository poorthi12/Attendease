import re

from pydantic import BaseModel, Field, field_validator


class SubjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=2, max_length=100)
    academic_year: str = Field(min_length=4, max_length=20)
    semester: str = Field(min_length=1, max_length=20)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9._-]+", normalized):
            raise ValueError("Subject code may contain letters, numbers, dots, underscores, and hyphens.")
        return normalized

    @field_validator("name", "department", "academic_year", "semester")
    @classmethod
    def trim_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized
