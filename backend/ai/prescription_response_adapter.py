"""처방 검색 내부 결과를 기존 서비스 응답 모델로 변환한다.

DB·모델·네트워크를 호출하지 않으며 ID나 원문 조회 경로를 생성하지 않는다.
서비스 계층이 상담·병증 검색·선택 병증의 접근권한과 관계를 먼저 확인하고,
발급된 검색 ID와 실제로 구현된 원문 조회 경로 생성 함수를 전달해야 한다.
형식 검증만으로 실제 DB 레코드나 조회 경로의 존재를 입증하지 않는다.
내부 원문·추적 정보는 입력 결과에 보존되고, 응답에는 모델이 정의한 값만 담긴다.
"""
from collections import Counter
from copy import deepcopy
import math
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .schemas import PrescriptionSearchRequest, PrescriptionSearchResult


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _saved_search_id(value: str) -> str:
    _require(type(value) is str and bool(value.strip()), '저장용 검색 ID가 필요합니다.')
    _require(value == value.strip(), '검색 ID에 앞뒤 공백이 있습니다.')
    _require(not value.lower().startswith('preview-'), '미리보기 ID를 저장용 검색 ID로 사용할 수 없습니다.')
    return value


def _source_url(value: str) -> str:
    _require(type(value) is str and bool(value), '서비스의 실제 원문 조회 경로가 필요합니다.')
    _require(value == value.strip() and not any(c.isspace() for c in value), '원문 조회 경로에 공백이 있습니다.')
    _require(value.startswith('/') and not value.startswith('//') and '\\' not in value, '원문 조회 경로는 서비스 내부 절대 경로여야 합니다.')
    parsed = urlsplit(value)
    _require(not parsed.scheme and not parsed.netloc and not parsed.fragment, '외부 주소나 조각 식별자를 원문 조회 경로로 사용할 수 없습니다.')
    return value


def _candidate(
    raw: Mapping[str, Any],
    symptoms: str,
    source_url_for: Callable[[Mapping[str, Any]], str],
) -> dict:
    evidence = []
    for source in raw['evidenceSources']:
        keys = (
            'sourceId', 'sourceTitle', 'dataVersion', 'fileName', 'sheet',
            'column', 'sourceLocation', 'itemId', 'row', 'excerpt',
        )
        projected = {key: deepcopy(source[key]) for key in keys}
        _require(source['itemId'] == raw['id'], '후보와 원문 근거의 항목 ID가 다릅니다.')
        # 호출자가 입력 근거 객체를 수정해도 원본 검색 결과에는 영향을 주지 않는다.
        projected['sourceUrl'] = _source_url(source_url_for(deepcopy(source)))
        evidence.append(projected)
    return {
        'id': raw['id'], 'name': raw['name'],
        'score': raw['score'], 'rank': raw['rank'],
        'evaluationStatus': raw['evaluationStatus'],
        'ingredients': deepcopy(raw['ingredients']),
        'caution': deepcopy(raw['caution']),
        'evidence': evidence,
        'explanation': {
            'status': 'NOT_REQUESTED', 'text': None,
            'message': 'AI 설명을 요청하지 않았습니다.',
            'checkedItems': [], 'uncheckedItems': ['AI 설명 생성'],
            'unexplainedSymptoms': [symptoms],
        },
    }


def build_prescription_search_response(
    raw_result: Mapping[str, Any],
    *,
    request: PrescriptionSearchRequest,
    search_id: str,
    source_url_for: Callable[[Mapping[str, Any]], str],
) -> PrescriptionSearchResult:
    """권한·DB 연결 검사를 마친 서비스 계층이 호출하는 순수 변환 함수.

    source_url_for는 필수이며 임의 경로를 기본값으로 제공하지 않는다.
    검색 결과의 평가·미평가 목록과 순서는 유지한다. 설명 작업을 시작하거나
    취소를 요청하지 않으므로 관련 상태는 각각 False다.
    """
    _require(isinstance(request, PrescriptionSearchRequest), '검증된 처방 검색 요청 모델이 필요합니다.')
    _require(isinstance(raw_result, Mapping), '처방 검색 결과는 객체여야 합니다.')
    _require(callable(source_url_for), '원문 조회 경로 생성 함수가 필요합니다.')
    saved_id = _saved_search_id(search_id)
    _require(raw_result['symptoms'] == request.symptoms, '요청과 검색 결과의 증상이 다릅니다.')
    _require(raw_result['selectedDiseaseId'] == request.selectedDiseases[0], '요청과 검색 결과의 선택 병증이 다릅니다.')
    _require(bool(raw_result['symptoms'].strip()), '검색 결과의 증상이 비어 있습니다.')

    result = PrescriptionSearchResult.model_validate({
        'kind': 'PRESCRIPTION', 'caseId': request.caseId,
        'diseaseSearchId': request.diseaseSearchId, 'searchId': saved_id,
        'selectedDiseaseId': raw_result['selectedDiseaseId'],
        'symptoms': raw_result['symptoms'],
        'candidates': [_candidate(c, request.symptoms, source_url_for) for c in raw_result['candidates']],
        'unscoredCandidates': [_candidate(c, request.symptoms, source_url_for) for c in raw_result['unscoredCandidates']],
        'summary': deepcopy(raw_result['summary']),
        'hasPendingExplanations': False, 'cancelRequested': False,
        'message': raw_result['message'],
    })
    all_candidates = result.candidates + result.unscoredCandidates
    _require(len({c.id for c in all_candidates}) == len(all_candidates), '평가·미평가 목록에 중복 처방이 있습니다.')
    for rank, candidate in enumerate(result.candidates, start=1):
        _require(candidate.evaluationStatus == 'SCORED', '평가 목록에 미평가 처방이 있습니다.')
        _require(candidate.rank == rank, '평가 후보 순위가 연속적이지 않습니다.')
        _require(candidate.score is not None and math.isfinite(candidate.score) and -1 <= candidate.score <= 1, '연관성 점수가 유효하지 않습니다.')
        _require(bool(candidate.evidence), '평가한 처방의 원문 근거가 없습니다.')
    for candidate in result.unscoredCandidates:
        _require(candidate.evaluationStatus != 'SCORED', '미평가 목록에 평가된 처방이 있습니다.')
        _require(candidate.score is None and candidate.rank is None, '미평가 처방에 점수나 순위가 있습니다.')
    counts = Counter(c.evaluationStatus for c in all_candidates)
    expected = {
        'connectedCount': len(all_candidates),
        'scoredCount': counts['SCORED'],
        'insufficientCount': counts['INSUFFICIENT_DATA'],
        'policyUnconfiguredCount': counts['POLICY_NOT_CONFIGURED'],
    }
    _require(result.summary.model_dump() == expected, '처방 목록과 요약 건수가 다릅니다.')
    # 기존 모델의 정규화로도 용량·단위·이름 등 원문이 조용히 변경되지 않게 한다.
    for raw_group, output_group in ((raw_result['candidates'], result.candidates), (raw_result['unscoredCandidates'], result.unscoredCandidates)):
        for raw, converted in zip(raw_group, output_group):
            _require([i.model_dump() for i in converted.ingredients] == raw['ingredients'], '변환 중 약재 원문이 변경됐습니다.')
            _require(converted.caution.model_dump() == raw['caution'], '변환 중 주의정보가 변경됐습니다.')
    return result
