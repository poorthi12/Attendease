import re

from pydantic import BaseModel, EmailStr, Field, field_validator


class StudentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    usn: str = Field(min_length=3, max_length=32)
    branch: str = Field(min_length=2, max_length=100)
    department: str = Field(min_length=2, max_length=100)
    academic_year: str = Field(min_length=4, max_length=20)

    @field_validator("usn")
    @classmethod
    def normalize_usn(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]+", normalized):
            raise ValueError("USN may contain letters, numbers, and hyphens only.")
        return normalized

    @field_validator("name", "branch", "department", "academic_year")
    @classmethod
    def trim_profile_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("This field must contain at least two non-space characters.")
        return value
