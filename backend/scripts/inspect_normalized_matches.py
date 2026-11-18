import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.ai import normalized_matching
from backend.ai.normalized_matching import (
    MATCH_POLICY_VERSION,
    build_keyword_index,
    find_normalized_matches,
)


def fingerprint(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="정규화 표현 일치 후보 기록")
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--diseases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")

    source = json.loads(args.analysis.read_text(encoding="utf-8"))
    if source["settings"]["policy_version"] != "kiwi_split_complex_units_v1":
        raise ValueError("이번 일치 검사와 다른 정규화 정책입니다.")

    diseases = [
        json.loads(line)
        for line in args.diseases.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    names = {row["DIS_UNIQN"]: row["ATT_DIS_NM"] for row in diseases}
    if len(names) != len(diseases):
        raise ValueError("병증 원문에 중복 식별번호가 있습니다.")
    if any(link["disease_id"] not in names for link in source["keyword_links"]):
        raise ValueError("등록 표현에 연결된 병증 원문이 없습니다.")

    index = build_keyword_index(
        source["registered_terms"], source["keyword_links"]
    )
    records = []
    for case in source["cases"]:
        text = case["input_text"]
        matches = find_normalized_matches(text, case, index)
        for match in matches:
            match["disease_name"] = names[match["disease_id"]]
        records.append({
            "case_id": case["case_id"],
            "input_text": text,
            "keyword_matches": matches,
        })

    report = {
        "report_version": "normalized_match_trace_v1",
        "purpose": "표현 일치 후보 검사. 증상·부정 판정과 검색 순위 반영 전.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "match_policy_version": MATCH_POLICY_VERSION,
        "normalization_settings": source["settings"],
        "source_analysis": fingerprint(args.analysis),
        "disease_source": fingerprint(args.diseases),
        "script": fingerprint(Path(__file__)),
        "matcher_script": fingerprint(Path(normalized_matching.__file__)),
        "summary": {
            "query_count": len(records),
            "keyword_row_count": len(source["keyword_links"]),
            "indexed_link_count": index["indexed_link_count"],
            "skipped_link_count": len(index["skipped_links"]),
            "cases_with_expression_matches": sum(
                bool(case["keyword_matches"]) for case in records
            ),
            "unassessed_match_count": sum(
                len(case["keyword_matches"]) for case in records
            ),
        },
        "skipped_links": index["skipped_links"],
        "cases": records,
    }
    serialized = json.dumps(
        report, ensure_ascii=False, indent=2, allow_nan=False
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(serialized + "\n")
    if json.loads(args.output.read_text(encoding="utf-8")) != report:
        raise ValueError("저장한 표현 일치 기록이 일치하지 않습니다.")

    print("등록 연결:", len(source["keyword_links"]), "행")
    print("비교 가능한 연결:", index["indexed_link_count"], "행")
    print("비교 제외:", len(index["skipped_links"]), "행")
    for case in records:
        terms = sorted({
            row["registered_term"] for row in case["keyword_matches"]
        })
        print(case["case_id"], case["input_text"])
        print("표현 일치 후보:", terms)
    print("미판정 일치 기록:", report["summary"]["unassessed_match_count"], "건")
    print("부정·증상 문맥 판정: 미실행 / 검색 순위 반영: 미실행")
    print("저장 완료:", args.output)
    print("정규화 표현 일치 기록 저장·재조회 확인 완료")


if __name__ == "__main__":
    main()

