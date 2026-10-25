import re

from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class SignupBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Enter your full name.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("The passwords do not match.")
        return self


def _valid_subject_ids(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("A subject can only be selected once.")
    if any(not ObjectId.is_valid(value) for value in values):
        raise ValueError("Choose subjects from the list.")
    return values


class StudentSignup(SignupBase):
    usn: str = Field(min_length=3, max_length=32)
    branch: str = Field(min_length=2, max_length=100)
    group_id: str = Field(min_length=24, max_length=24)
    subject_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("usn")
    @classmethod
    def normalize_usn(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]+", normalized):
            raise ValueError("USN may contain letters, numbers, and hyphens only.")
        return normalized

    @field_validator("branch")
    @classmethod
    def normalize_branch(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Enter your branch.")
        return normalized

    @field_validator("subject_ids")
    @classmethod
    def validate_subject_ids(cls, values: list[str]) -> list[str]:
        return _valid_subject_ids(values)


class TeacherSignup(SignupBase):
    department: str = Field(min_length=2, max_length=100)
    subject_ids: list[str] = Field(min_length=1, max_length=128)

    @field_validator("department")
    @classmethod
    def normalize_department(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Choose your department.")
        return normalized

    @field_validator("subject_ids")
    @classmethod
    def validate_subject_ids(cls, values: list[str]) -> list[str]:
        return _valid_subject_ids(values)
