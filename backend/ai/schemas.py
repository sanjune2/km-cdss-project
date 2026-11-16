from typing import Literal

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

class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sourceId: str = Field(description="근거 자료 식별자")
    sourceTitle: str = Field(description="근거 자료 제목")
    dataVersion: str = Field(description="근거 자료 버전")
    sourceUrl: str = Field(description="서비스 내 원문 조회 경로")

    fileName: str = Field(description="기업 원본 파일명")
    sheet: str = Field(description="원본 시트명")
    column: str = Field(description="원본 컬럼명")
    sourceLocation: str = Field(description="원문 위치")

    itemId: int = Field(gt=0, description="기업 항목 식별번호")
    row: int = Field(gt=0, description="원본 엑셀 행번호")

    excerpt: str = Field(description="실제 원문 발췌")

class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[
        "NOT_REQUESTED",
        "QUEUED",
        "RUNNING",
        "READY",
        "WITHHELD",
        "INCOMPLETE",
    ] = Field(description="AI 설명 처리 상태")

    text: str | None = Field(description="제공 가능한 AI 참고 설명")
    message: str | None = Field(description="처리 상태 또는 보류 사유")

    checkedItems: list[str] = Field(description="확인한 항목")
    uncheckedItems: list[str] = Field(description="확인하지 못한 항목")
    unexplainedSymptoms: list[str] = Field(
        description="제공된 근거로 설명하지 못한 입력 증상"
    )