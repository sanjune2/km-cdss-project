"""DB·모델 호출 없이 처방 검색 자료와 서비스 응답 형식의 준비 상태를 검사한다."""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

import numpy as np
from pydantic import ValidationError

from backend.ai.prescription_search import get_linked_prescriptions, search_prescriptions
from backend.ai.schemas import PrescriptionCandidate, PrescriptionSearchResult


class FixedQuery:
    """구조 검사에만 쓰며 증상의 의미나 추천 품질은 평가하지 않는다."""
    def __init__(self):
        self.calls = 0

    def encode_query(self, symptoms):
        self.calls += 1
        result = np.zeros(384, dtype=np.float32)
        result[0] = 1.0
        return result


def read_jsonl(path):
    with path.open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify(data_root, output):
    root = data_root.resolve()
    paths = {
        'diseases': root / 'stage1/검색용/병증원문.jsonl',
        'prescriptions': root / 'stage1/검색용/처방원문.jsonl',
        'relations': root / 'stage1/조회용/병증처방관계.jsonl',
        'compositions': root / 'stage1/조회용/처방약재구성.jsonl',
        'herbs': root / 'stage1/조회용/약재원문.jsonl',
        'chunks': root / 'stage2/청킹결과.jsonl',
        'matrix': root / 'stage2/벡터행렬.npy',
    }
    check(output.suffix.lower() == '.json', '출력 파일은 .json이어야 합니다.')
    # 시험 결과를 원본 자료 폴더에 쓰지 않는다.
    check(not output.resolve().is_relative_to(root), '출력은 data-root 밖의 별도 폴더를 사용해주세요.')
    before = {name: digest(path) for name, path in paths.items()}
    data = {name: read_jsonl(path) for name, path in paths.items() if name != 'matrix'}
    matrix = np.load(paths['matrix'], allow_pickle=False)
    presps = data['prescriptions']
    presp_ids = {row['PRESP_UNIQN'] for row in presps}
    disease_ids = {row['DIS_UNIQN'] for row in data['diseases']}
    herb_by_id = {row['MED_UNIQN']: row for row in data['herbs']}
    composition_by_id = {row['RSHIP_UNIQN']: row for row in data['compositions']}
    check(len(presp_ids) == len(presps), '처방 ID 중복')
    check(len(disease_ids) == len(data['diseases']), '병증 ID 중복')
    check(len(herb_by_id) == len(data['herbs']), '약재 ID 중복')
    check(len(composition_by_id) == len(data['compositions']), '처방약재 관계 ID 중복')
    check(all(r['DIS_UNIQN'] in disease_ids and r['PRESP_UNIQN'] in presp_ids for r in data['relations']), '병증처방 관계 연결 오류')
    check(all(r['PRESP_UNIQN'] in presp_ids and r['MED_UNIQN'] in herb_by_id for r in data['compositions']), '처방약재 관계 연결 오류')

    query = FixedQuery()
    unique_candidates = {}
    envelope_missing = set()
    required_result = {name for name, field in PrescriptionSearchResult.model_fields.items() if field.is_required()}
    for disease_id in sorted(disease_ids):
        linked = get_linked_prescriptions(disease_id, data['diseases'], presps, data['relations'])
        expected_ids = {r['PRESP_UNIQN'] for r in data['relations'] if r['DIS_UNIQN'] == disease_id}
        check({r['PRESP_UNIQN'] for r in linked} == expected_ids, '선택 병증의 연결 처방 누락')
        result = search_prescriptions(
            '응답 구조 검사 전용 문장', disease_id, query, data['diseases'], presps,
            data['relations'], data['chunks'], matrix, data['compositions'], data['herbs'],
        )
        candidates = result['candidates'] + result['unscoredCandidates']
        returned_ids = [row['id'] for row in candidates]
        check(len(returned_ids) == len(set(returned_ids)), '후보 중복')
        check(set(returned_ids) == expected_ids, '평가·미평가 목록에서 연결 처방 누락')
        summary = result['summary']
        check(summary['connectedCount'] == len(candidates), '연결 건수 불일치')
        check(summary['scoredCount'] == len(result['candidates']), '평가 건수 불일치')
        check(summary['insufficientCount'] == len(result['unscoredCandidates']), '자료 부족 건수 불일치')
        check([c['rank'] for c in result['candidates']] == list(range(1, len(result['candidates']) + 1)), '평가 후보 순위 오류')
        envelope_missing.update(required_result - result.keys())
        for candidate in candidates:
            unique_candidates.setdefault(candidate['id'], candidate)

    evidence_count = 0
    ingredient_count = 0
    no_composition = []
    schema_errors = Counter()
    schema_samples = []
    for prescription_id, candidate in sorted(unique_candidates.items()):
        expected_rows = [r for r in data['compositions'] if r['PRESP_UNIQN'] == prescription_id]
        ingredients = candidate['ingredients']
        check([i['compositionId'] for i in ingredients] == [r['RSHIP_UNIQN'] for r in expected_rows], '약재 구성 누락·순서 변경')
        for ingredient in ingredients:
            original = composition_by_id[ingredient['compositionId']]
            check(ingredient['id'] == original['MED_UNIQN'], '약재 ID 불일치')
            check(ingredient['name'] == herb_by_id[ingredient['id']]['MED_NM'], '약재명 원문 불일치')
            for target, source in [('amount', 'UNT_COEFF'), ('unit', 'UNT'), ('preparation', 'MED_SPEC_REP'), ('originalDoseInfo', 'CC_INFO')]:
                value = original[source]
                expected = value if value is not None and value.strip() else None
                check(ingredient[target] == expected, '약재 용량·단위·가공·용법 원문 변경')
                check(ingredient[target] is None or isinstance(ingredient[target], str), '약재 원문 자료형 변경')
            ingredient_count += 1
        if not ingredients:
            no_composition.append(prescription_id)
        if candidate['evaluationStatus'] == 'SCORED':
            check(bool(candidate['evidenceSources']), '평가 후보의 근거 누락')
            evidence_count += len(candidate['evidenceSources'])
        else:
            check(candidate['score'] is None and candidate['rank'] is None, '미평가 후보 점수·순위 부여')
        check(candidate['caution']['status'] == 'RULES_NOT_REVIEWED', '주의정보를 검토 완료로 잘못 표시')
        check(candidate['caution']['registeredTexts'] == [r['text'] for r in candidate['cautionSources']], '주의 원문 연결 불일치')
        try:
            PrescriptionCandidate.model_validate(candidate)
        except ValidationError as error:
            for item in error.errors(include_input=False, include_url=False):
                key = '.'.join(map(str, item['loc'])) + ':' + item['type']
                schema_errors[key] += 1
            if len(schema_samples) < 3:
                schema_samples.append({'prescriptionId': prescription_id, 'errors': error.errors(include_input=False, include_url=False)})

    after = {name: digest(path) for name, path in paths.items()}
    check(before == after, '검사 전후 원본 자료 해시 변경')
    report = {
        'scope': 'OFFLINE_PRESCRIPTION_STRUCTURE_AND_CONTRACT',
        'data_integrity': 'PASSED',
        'contract_status': 'ADAPTER_REQUIRED' if envelope_missing or schema_errors else 'CANDIDATE_AND_REQUIRED_KEYS_MATCH',
        'clinical_quality_evaluated': False,
        'query_vector': 'SYNTHETIC_FIXED_VECTOR_NOT_A_SYMPTOM_EMBEDDING',
        'real_db_calls': 0, 'real_model_calls': 0, 'network_calls': 0,
        'sql_writes_executed': False, 'history_saved': False,
        'input_counts': {name: len(rows) for name, rows in data.items()},
        'diseases_checked': len(disease_ids),
        'unique_prescriptions_checked': len(unique_candidates),
        'evaluation_counts': dict(Counter(c['evaluationStatus'] for c in unique_candidates.values())),
        'evidence_records_checked': evidence_count,
        'ingredient_records_checked': ingredient_count,
        'prescriptions_without_composition_count': len(no_composition),
        'prescriptions_without_composition_ids': no_composition,
        'missing_result_fields': sorted(envelope_missing),
        'candidate_schema_error_counts': dict(sorted(schema_errors.items())),
        'candidate_schema_error_samples': schema_samples,
        'source_hashes_unchanged': before == after,
        'source_sha256': before,
        'note': '원문·구조 검사이며 실제 서비스 응답·로그인·DB 연결·추천 품질 검증은 아님. 가짜 검색 ID나 원문 URL을 생성하지 않음.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ['data_integrity', 'contract_status', 'diseases_checked', 'unique_prescriptions_checked', 'evaluation_counts', 'ingredient_records_checked', 'missing_result_fields', 'source_hashes_unchanged', 'real_db_calls', 'real_model_calls']}, ensure_ascii=False, indent=2))
    print('검사 결과 저장:', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('출력 파일이 이미 있습니다. 새 파일명을 지정해주세요.')
    verify(args.data_root, args.output)


if __name__ == '__main__':
    main()
