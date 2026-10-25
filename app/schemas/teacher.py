from pydantic import BaseModel, EmailStr, Field, field_validator


class TeacherCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    department: str = Field(min_length=2, max_length=100)

    @field_validator("name", "department")
    @classmethod
    def trim_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("This field must contain at least two non-space characters.")
        return normalized
