"""실제 로컬 E5 모델로 처방 검색 한 건을 확인한다. DB·서비스 API에는 연결하지 않는다."""
import argparse
import json
import os
import sys
from pathlib import Path
from time import perf_counter

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

import numpy as np

from backend.ai.embedding import E5Embedder, MODEL_ID, MODEL_REVISION
from backend.ai.prescription_search import get_linked_prescriptions, search_prescriptions
from backend.scripts.verify_prescription_readiness import check, digest, read_jsonl


class CountedEmbedder:
    def __init__(self, embedder):
        self.embedder = embedder
        self.calls = 0

    def encode_query(self, symptoms):
        self.calls += 1
        return self.embedder.encode_query(symptoms)


def run(data_root, symptoms, disease_id, output):
    started = perf_counter()
    root = data_root.resolve()
    check(not output.resolve().is_relative_to(root), '결과는 원본 자료 폴더 밖에 저장해주세요.')
    check(output.suffix.lower() == '.json', '출력 파일은 .json이어야 합니다.')
    text = symptoms.strip()
    check(bool(text), '증상을 입력해주세요.')
    paths = {
        'diseases': root / 'stage1/검색용/병증원문.jsonl',
        'prescriptions': root / 'stage1/검색용/처방원문.jsonl',
        'relations': root / 'stage1/조회용/병증처방관계.jsonl',
        'compositions': root / 'stage1/조회용/처방약재구성.jsonl',
        'herbs': root / 'stage1/조회용/약재원문.jsonl',
        'chunks': root / 'stage2/청킹결과.jsonl',
        'matrix': root / 'stage2/벡터행렬.npy',
    }
    before = {name: digest(path) for name, path in paths.items()}
    data = {name: read_jsonl(path) for name, path in paths.items() if name != 'matrix'}
    matrix = np.load(paths['matrix'], allow_pickle=False)
    linked = get_linked_prescriptions(disease_id, data['diseases'], data['prescriptions'], data['relations'])
    check(bool(linked), '선택 병증에 연결된 처방이 없습니다. 다른 검증 병증을 선택해주세요.')
    disease = next(row for row in data['diseases'] if row['DIS_UNIQN'] == disease_id)
    print('단계: LOCAL_E5_LOADING', flush=True)
    loading = perf_counter()
    embedder = CountedEmbedder(E5Embedder())
    model_load_seconds = perf_counter() - loading
    print('단계: PRESCRIPTION_SEARCH_RUNNING', flush=True)
    searching = perf_counter()
    result = search_prescriptions(
        text, disease_id, embedder, data['diseases'], data['prescriptions'], data['relations'],
        data['chunks'], matrix, data['compositions'], data['herbs'],
    )
    search_seconds = perf_counter() - searching
    candidates = result['candidates'] + result['unscoredCandidates']
    check({c['id'] for c in candidates} == {row['PRESP_UNIQN'] for row in linked}, '검색 결과에서 연결 처방이 누락됐습니다.')
    check(len(candidates) == len(linked), '검색 결과에 중복 처방이 있습니다.')
    check(result['summary']['connectedCount'] == len(linked), '연결 건수 불일치')
    check(result['summary']['scoredCount'] == len(result['candidates']), '평가 건수 불일치')
    check(result['summary']['insufficientCount'] == len(result['unscoredCandidates']), '미평가 건수 불일치')
    check(embedder.calls == 1, '입력 임베딩 호출 건수가 다릅니다.')
    after = {name: digest(path) for name, path in paths.items()}
    check(before == after, '원본 자료의 해시가 변경됐습니다.')
    report = {
        'scope': 'LOCAL_PRESCRIPTION_SEARCH_PREVIEW', 'status': 'COMPLETED',
        'selectedDiseaseName': disease['ATT_DIS_NM'],
        'model': {'id': MODEL_ID, 'revision': MODEL_REVISION, 'device': 'cpu', 'local_cache_only': True},
        'query_embedding_calls': embedder.calls, 'generation_calls': 0,
        'synthetic_query_vector': False, 'real_db_calls': 0,
        'sql_writes_executed': False, 'history_saved': False,
        'source_hashes_unchanged': True,
        'service_integration_verified': False, 'clinical_quality_evaluated': False,
        'timing_seconds': {
            'model_load': round(model_load_seconds, 3),
            'query_embedding_and_search': round(search_seconds, 3),
            'total_before_save': round(perf_counter() - started, 3),
        },
        'source_sha256': before, 'result': result,
        'note': '개발용 단일 검색 결과이며 적합한 처방이나 환자별 안전성을 확정하지 않음. 상담·검색 ID 발급 및 서비스 응답 변환은 수행하지 않음.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({
        'status': report['status'], 'selectedDiseaseId': disease_id,
        'selectedDiseaseName': report['selectedDiseaseName'],
        'summary': result['summary'],
        'top3': [{key: candidate[key] for key in ['id', 'name', 'rank', 'score']} for candidate in result['candidates'][:3]],
        'query_embedding_calls': embedder.calls, 'real_db_calls': 0,
        'source_hashes_unchanged': True, 'timing_seconds': report['timing_seconds'],
    }, ensure_ascii=False, indent=2))
    print('검사 결과 저장:', output)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--symptoms', required=True)
    parser.add_argument('--disease-id', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():parser.error('출력 파일이 이미 있습니다. 새 파일명을 지정해주세요.')
    run(args.data_root, args.symptoms, args.disease_id, args.output)


if __name__ == '__main__':
    main()
