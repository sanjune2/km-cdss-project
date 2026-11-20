"""실제 자료·합성 벡터·가상 ID로 응답 변환만 검사한다. 서비스에는 요청하지 않는다."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from backend.ai.prescription_response_adapter import build_prescription_search_response
from backend.ai.prescription_search import search_prescriptions
from backend.ai.schemas import PrescriptionSearchRequest, PrescriptionSearchResult
from backend.scripts.verify_prescription_readiness import FixedQuery, check, digest, read_jsonl


def fixture_source_url(source):
    # 형식 검증 전용 주소다. 실제 구현된 API 주소가 아니며 호출하지 않는다.
    return '/__offline_fixture__/sources/' + str(source['itemId'])


def fixture_request(disease_id, symptoms='응답 변환 검사 전용 문장'):
    # 실제 DB ID가 아니며 이 검사 밖의 서비스 요청에 사용할 수 없다.
    return PrescriptionSearchRequest(
        caseId=900000001, diseaseSearchId='900000002',
        selectedDiseases=[disease_id], symptoms=symptoms,
    )


def adapt(raw, request=None, search_id='900000003', resolver=fixture_source_url):
    return build_prescription_search_response(
        raw, request=request or fixture_request(raw['selectedDiseaseId']),
        search_id=search_id, source_url_for=resolver,
    )


def verify(data_root, output):
    root = data_root.resolve()
    check(not output.resolve().is_relative_to(root), '출력은 원본 자료 폴더 밖에 저장해주세요.')
    check(output.suffix.lower() == '.json', '출력 파일은 .json이어야 합니다.')
    paths = {
        'diseases': root / 'stage1/검색용/병증원문.jsonl',
        'prescriptions': root / 'stage1/검색용/처방원문.jsonl',
        'relations': root / 'stage1/조회용/병증처방관계.jsonl',
        'compositions': root / 'stage1/조회용/처방약재구성.jsonl',
        'herbs': root / 'stage1/조회용/약재원문.jsonl',
        'chunks': root / 'stage2/청킹결과.jsonl',
        'matrix': root / 'stage2/벡터행렬.npy',
    }
    before = {key: digest(path) for key, path in paths.items()}
    data = {key: read_jsonl(path) for key, path in paths.items() if key != 'matrix'}
    matrix = np.load(paths['matrix'], allow_pickle=False)
    query = FixedQuery()
    verified = {}
    sample = None
    expected_ids = {r['PRESP_UNIQN'] for r in data['relations']}
    for disease in data['diseases']:
        request = fixture_request(disease['DIS_UNIQN'])
        raw = search_prescriptions(
            request.symptoms, disease['DIS_UNIQN'], query, data['diseases'],
            data['prescriptions'], data['relations'], data['chunks'], matrix,
            data['compositions'], data['herbs'],
        )
        snapshot = deepcopy(raw)
        response = adapt(raw, request=request)
        check(raw == snapshot, '응답 변환이 입력 검색 결과를 변경했습니다.')
        check(response.caseId == request.caseId and response.diseaseSearchId == request.diseaseSearchId, '요청 ID 연결 오류')
        check(response.searchId == '900000003' and response.kind == 'PRESCRIPTION', '응답 ID·구분 오류')
        check(not response.hasPendingExplanations and not response.cancelRequested, '미실행 작업 상태 오류')
        check(response.message == raw['message'], '안내 문구 변경')
        roundtrip = PrescriptionSearchResult.model_validate(json.loads(response.model_dump_json()))
        check(roundtrip == response, 'JSON 전송 형식 재검증 실패')
        for key, group in [('candidates', response.candidates), ('unscoredCandidates', response.unscoredCandidates)]:
            check([c.id for c in group] == [c['id'] for c in raw[key]], '처방 순서 또는 ID 변경')
            for original, converted in zip(raw[key], group):
                check(converted.score == original['score'] and converted.rank == original['rank'], '점수·순위 변경')
                check(converted.name == original['name'] and converted.evaluationStatus == original['evaluationStatus'], '처방명·평가 상태 변경')
                check(converted.explanation.status == 'NOT_REQUESTED' and converted.explanation.text is None, '미생성 설명을 완료로 표시')
                for source, evidence in zip(original['evidenceSources'], converted.evidence):
                    check(evidence.sourceUrl == fixture_source_url(source), '원문 경로 연결 오류')
                    for field, value in evidence.model_dump().items():
                        if field != 'sourceUrl':check(value == source[field], '원문 근거 변경')
                check(len(converted.evidence) == len(original['evidenceSources']), '원문 근거 개수 변경')
                check([i.model_dump() for i in converted.ingredients] == original['ingredients'], '약재 원문 변경')
                check(converted.caution.model_dump() == original['caution'], '주의정보 원문 변경')
                verified.setdefault(converted.id, converted)
        if raw['candidates'] and raw['unscoredCandidates'] and sample is None:
            sample = snapshot
    check(set(verified) == expected_ids, '전체 연결 처방 누락')
    check(sample is not None, '평가·미평가 경계 검사에 필요한 예제가 없습니다.')
    checks = []

    def reject(name, callback):
        try:
            callback()
        except (ValueError, TypeError):
            checks.append({'check': name, 'passed': True})
            return
        raise AssertionError(name + ': 잘못된 입력을 거부하지 않았습니다.')

    reject('빈 저장용 검색 ID 거부', lambda: adapt(sample, search_id=''))
    reject('미리보기 ID의 저장용 사용 거부', lambda: adapt(sample, search_id='preview-example'))
    reject('병증 미리보기 ID 거부', lambda: PrescriptionSearchRequest(caseId=1, diseaseSearchId='preview-example', selectedDiseases=[sample['selectedDiseaseId']], symptoms=sample['symptoms']))
    reject('원문 경로 함수 누락 거부', lambda: build_prescription_search_response(sample, request=fixture_request(sample['selectedDiseaseId']), search_id='900000003'))
    reject('빈 원문 경로 거부', lambda: adapt(sample, resolver=lambda _: ''))
    reject('외부 원문 경로 거부', lambda: adapt(sample, resolver=lambda _: 'https://example.invalid/source'))
    reject('요청과 다른 증상 거부', lambda: adapt(sample, request=fixture_request(sample['selectedDiseaseId'], '서로 다른 입력')))
    wrong_disease = deepcopy(sample)
    wrong_disease['selectedDiseaseId'] += 1
    reject('요청과 다른 병증 거부', lambda: adapt(wrong_disease, request=fixture_request(sample['selectedDiseaseId'])))
    wrong_summary = deepcopy(sample)
    wrong_summary['summary']['connectedCount'] += 1
    reject('요약 건수 불일치 거부', lambda: adapt(wrong_summary))
    duplicate = deepcopy(sample)
    duplicate['unscoredCandidates'].append(deepcopy(duplicate['candidates'][0]))
    reject('목록 간 중복 처방 거부', lambda: adapt(duplicate))
    unscored = deepcopy(sample)
    unscored['unscoredCandidates'][0]['score'] = 0.5
    reject('미평가 처방 점수 거부', lambda: adapt(unscored))
    no_evidence = deepcopy(sample)
    no_evidence['candidates'][0]['evidenceSources'] = []
    reject('평가 처방 근거 누락 거부', lambda: adapt(no_evidence))
    nonfinite = deepcopy(sample)
    nonfinite['candidates'][0]['score'] = float('nan')
    reject('유효하지 않은 점수 거부', lambda: adapt(nonfinite))
    wrong_evidence = deepcopy(sample)
    wrong_evidence['candidates'][0]['evidenceSources'][0]['itemId'] += 1
    reject('다른 처방의 원문 근거 거부', lambda: adapt(wrong_evidence))
    empty = {
        'selectedDiseaseId': sample['selectedDiseaseId'], 'symptoms': sample['symptoms'],
        'candidates': [], 'unscoredCandidates': [],
        'summary': {'connectedCount': 0, 'scoredCount': 0, 'insufficientCount': 0, 'policyUnconfiguredCount': 0},
        'message': '기업 자료에 연결된 처방이 없습니다',
    }
    def never_resolve(_):
        raise AssertionError('근거가 없는 결과에서 원문 경로 함수를 호출했습니다.')
    check(adapt(empty, resolver=never_resolve).summary.connectedCount == 0, '빈 결과 처리 오류')
    checks.append({'check': '연결 처방 없는 응답 보존', 'passed': True})
    after = {key: digest(path) for key, path in paths.items()}
    check(before == after, '원본 자료 해시 변경')
    report = {
        'scope': 'OFFLINE_RESPONSE_ADAPTER_ONLY', 'status': 'PASSED',
        'diseases_checked': len(data['diseases']), 'unique_prescriptions_checked': len(verified),
        'scored_prescriptions': sum(c.evaluationStatus == 'SCORED' for c in verified.values()),
        'unscored_prescriptions': sum(c.evaluationStatus != 'SCORED' for c in verified.values()),
        'ingredient_records_preserved': sum(len(c.ingredients) for c in verified.values()),
        'boundary_checks_passed': len(checks), 'checks': checks,
        'source_hashes_unchanged': True, 'input_results_unchanged': True,
        'synthetic_query_vector': True, 'fixture_ids_and_urls_only': True,
        'real_db_calls': 0, 'real_model_calls': 0, 'network_calls': 0,
        'sql_writes_executed': False, 'history_saved': False,
        'service_integration_verified': False, 'clinical_quality_evaluated': False,
        'source_sha256': before,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('checks', 'source_sha256')}, ensure_ascii=False, indent=2))
    print('검사 결과 저장:', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():parser.error('출력 파일이 이미 있습니다. 새 파일명을 지정해주세요.')
    verify(args.data_root, args.output)


if __name__ == '__main__':
    main()
