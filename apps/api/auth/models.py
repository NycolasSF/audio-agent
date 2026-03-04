from typing import List, Optional

from pydantic import BaseModel, EmailStr, field_validator


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    name: str = ""

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Senha deve ter pelo menos 8 caracteres")
        return v


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    quota_minutes: float
    usage_minutes: float


class UsageRecord(BaseModel):
    id: int
    job_id: Optional[str]
    minutes: float
    model: Optional[str]
    created_at: str


class UsageResponse(BaseModel):
    total_minutes: float
    quota_minutes: float
    remaining_minutes: float
    history: List[UsageRecord]
