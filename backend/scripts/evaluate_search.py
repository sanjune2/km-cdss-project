import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.ai.embedding import E5Embedder, MODEL_ID, MODEL_REVISION
from backend.ai.keyword_rules import INFLECTED_SYMPTOM_FORMS
from backend.ai.search import (
    KEYWORD_RRF_WEIGHT,
    MAX_KEYWORD_CANDIDATES,
    MAX_SEMANTIC_CANDIDATES,
    RRF_K,
    search_hybrid,
)
from backend.scripts.load_search_data import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="병증 검색 개발 대조")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 다른 파일명을 지정해주세요.")

    root = args.data_root
    queries = read_jsonl(root / "stage1/개발대조용/질의입력.jsonl")
    criteria = read_jsonl(root / "stage1/개발대조용/판정기준.jsonl")
    inputs = {row["case_id"]: row["input_text"] for row in queries}
    diseases = read_jsonl(root / "stage1/검색용/병증원문.jsonl")
    keywords = read_jsonl(root / "stage1/검색용/키워드검색항목.jsonl")
    chunks = read_jsonl(root / "stage2/청킹결과.jsonl")
    matrix = np.load(root / "stage2/벡터행렬.npy", allow_pickle=False)
    names = {row["DIS_UNIQN"]: row["ATT_DIS_NM"] for row in diseases}
    embedder = E5Embedder()
    records = []
    excluded = []

    for criterion in criteria:
        case_id = criterion["case_id"]
        if criterion["development_hit_check_eligible"] is not True:
            excluded.append({
                "caseId": case_id,
                "reason": criterion["eligibility_reason"],
            })
            continue

        expected_ids = criterion["expected_candidate_ids"]
        if not expected_ids or any(value not in names for value in expected_ids):
            raise ValueError(f"{case_id}: 기대 후보 식별번호를 확인해주세요.")

        result = search_hybrid(
            symptoms=inputs[case_id], embedder=embedder,
            diseases=diseases, keywords=keywords, chunks=chunks, matrix=matrix,
        )
        ranks = {row["id"]: row["rank"] for row in result["candidates"]}
        found_ranks = [ranks[value] for value in expected_ids if value in ranks]
        best_rank = min(found_ranks) if found_ranks else None
        records.append({
            "caseId": case_id,
            "category": criterion["category"],
            "input": inputs[case_id],
            "expectedCandidates": [
                {"id": value, "name": names[value], "rank": ranks.get(value)}
                for value in expected_ids
            ],
            "expectedCandidatesExhaustive": criterion["expected_candidates_exhaustive"],
            "expectedBestRank": best_rank,
            "inTop1": best_rank == 1,
            "inTop3": best_rank is not None and best_rank <= 3,
            "inReturnedResults": best_rank is not None,
            "sourceLocation": criterion["source_location_record_original"],
            "overlapAudit": criterion["overlap_audit"],
            "searchResult": result,
        })
        print(f"{case_id}: 기대 후보 순위 {best_rank if best_rank is not None else '결과에 없음'}")

    summary = {
        "totalCases": len(criteria),
        "completedCases": len(records),
        "excludedCases": len(excluded),
        "top1IncludedCases": sum(row["inTop1"] for row in records),
        "top3IncludedCases": sum(row["inTop3"] for row in records),
        "returnedIncludedCases": sum(row["inReturnedResults"] for row in records),
    }
    report = {
        "purpose": "개발 대조용. 독립적인 최종 평가 또는 임상 정확도가 아님.",
        "explanationEvaluation": "미실행",
        "executedAt": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "dataRoot": str(root.resolve()),
            "modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
            "rrfK": RRF_K,
            "keywordRrfWeight": float(KEYWORD_RRF_WEIGHT),
            "semanticRrfWeight": 1.0,
            "keywordRankPolicy": "all_tied_first",
            "inflectionPolicy": "explicit_forms_v1",
            "inflectedSymptomForms": INFLECTED_SYMPTOM_FORMS,
            "negationPolicy": "explicit_adjacent_prefix_suffix_v1",
            "negationPrefixTerms": ["안", "못"],
            "negationScope": "keyword_matches_only",
            "maxKeywordCandidates": MAX_KEYWORD_CANDIDATES,
            "maxSemanticCandidates": MAX_SEMANTIC_CANDIDATES,
        },
        "summary": summary, "cases": records, "excluded": excluded,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("저장 완료:", args.output)


if __name__ == "__main__":
    main()
