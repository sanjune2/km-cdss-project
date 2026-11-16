from pydantic import BaseModel, ConfigDict, Field, field_validator


class SymptomSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    caseId: int = Field(gt=0, description="상담기록 식별번호")
    symptoms: str = Field(description="한의사가 입력한 증상")

    @field_validator("symptoms")
    @classmethod
    def clean_symptoms(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("증상을 입력해주세요.")

        return value