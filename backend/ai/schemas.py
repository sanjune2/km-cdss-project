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

class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(gt=0, description="기업 항목 식별번호")
    name: str = Field(description="후보 이름")

    score: float | None = Field(description="서버가 계산한 점수")
    rank: int | None = Field(gt=0, description="결과 순위")

    evidence: list[Evidence] = Field(description="기업 원문 근거 목록")
    explanation: Explanation = Field(description="AI 설명과 처리 상태")

class DiseaseSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["DISEASE"] = Field(description="병증 검색 결과 구분")

    caseId: int = Field(gt=0, description="상담기록 식별번호")
    searchId: str = Field(description="이번 검색의 식별번호")
    symptoms: str = Field(description="이번 검색에 사용한 증상")

    candidates: list[Candidate] = Field(description="병증 후보 전체 목록")
    total: int = Field(ge=0, description="반환한 후보 전체 건수")

    hasPendingExplanations: bool = Field(
        description="대기 또는 처리 중인 설명 작업 존재 여부"
    )
    cancelRequested: bool = Field(description="작업 중단 요청 접수 여부")

    message: str | None = Field(description="검색 결과 안내")

class PrescriptionSearchRequest(SymptomSearchRequest):
    diseaseSearchId: str = Field(
        pattern=r"^[0-9]+$",
        description="병증 검색 응답으로 받은 검색 식별번호",
    )

    selectedDiseases: list[int] = Field(
        min_length=1,
        max_length=1,
        description="선택한 기업 병증 식별번호 한 개",
    )

    @field_validator("selectedDiseases")
    @classmethod
    def validate_selected_disease(cls, value: list[int]) -> list[int]:
        if value[0] <= 0:
            raise ValueError("병증 식별번호는 1 이상이어야 합니다.")

        return value

class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    compositionId: int | None = Field(
        gt=0,
        description="기업 원본의 처방·약재 구성 행 식별번호",
    )
    id: int | None = Field(gt=0, description="약재 식별번호")
    name: str = Field(description="약재명")

    amount: str | None = Field(description="원본 용량 수치의 소수 문자열")
    unit: str | None = Field(description="원본 용량 단위")
    preparation: str | None = Field(description="원본 가공법")
    originalDoseInfo: str | None = Field(description="원본 용량·용법 기록")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("약재명을 입력해주세요.")

        return value

class Caution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[
        "RULES_NOT_REVIEWED",
        "PATIENT_INFO_INSUFFICIENT",
        "SOURCE_NOT_REGISTERED",
        "CHECKED",
        "INCOMPLETE",
    ] = Field(description="주의정보 대조 상태")

    registeredTexts: list[str] = Field(
        description="기업 자료에 등록된 주의·부작용·금기 원문"
    )

    message: str | None = Field(description="대조 상태와 미완료 사유 안내")

class PrescriptionCandidate(Candidate):
    evaluationStatus: Literal[
        "SCORED",
        "INSUFFICIENT_DATA",
        "POLICY_NOT_CONFIGURED",
    ] = Field(description="처방 연관성 평가 상태")

    ingredients: list[Ingredient] = Field(description="처방의 약재 구성 목록")
    caution: Caution = Field(description="등록된 주의정보와 대조 상태")

class PrescriptionSearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    connectedCount: int = Field(
        ge=0,
        description="선택 병증에 연결된 처방 전체 건수",
    )
    scoredCount: int = Field(
        ge=0,
        description="연관성 평가를 완료한 처방 건수",
    )
    insufficientCount: int = Field(
        ge=0,
        description="평가 자료가 부족한 처방 건수",
    )
    policyUnconfiguredCount: int = Field(
        ge=0,
        description="평가 정책 미설정으로 평가하지 못한 처방 건수",
    )

class PrescriptionSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["PRESCRIPTION"] = Field(
        description="처방 검색 결과 구분"
    )

    caseId: int = Field(gt=0, description="상담기록 식별번호")
    selectedDiseaseId: int = Field(
        gt=0,
        description="선택한 기업 병증 식별번호",
    )

    diseaseSearchId: str = Field(description="연결된 병증 검색 식별번호")
    searchId: str = Field(description="이번 처방 검색의 식별번호")
    symptoms: str = Field(description="이번 검색에 사용한 증상")

    candidates: list[PrescriptionCandidate] = Field(
        description="연관성 평가를 완료한 처방 후보 목록"
    )
    unscoredCandidates: list[PrescriptionCandidate] = Field(
        description="자료 부족 또는 정책 미설정으로 미평가된 처방 목록"
    )
    summary: PrescriptionSearchSummary = Field(
        description="연결 처방의 평가 상태별 건수"
    )

    hasPendingExplanations: bool = Field(
        description="대기 또는 처리 중인 설명 작업 존재 여부"
    )
    cancelRequested: bool = Field(description="작업 중단 요청 접수 여부")

    message: str | None = Field(description="처방 검색 결과 안내")