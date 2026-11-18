"""LLM 재실행 없이 저장된 문맥 판정과 기존 키워드 검색의 후보를 비교한다."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.ai import context_candidate_policy as policy
from backend.ai import search as legacy_search
from backend.ai import keyword_rules


def fingerprint(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_verified(ref):
    if fingerprint(ref["path"])["sha256"] != ref["sha256"]:
        raise ValueError(f"저장 이후 참조 원본이 변경됐습니다: {ref['path']}")
    return read_json(ref["path"])


def link_identity(row):
    return tuple(row[k] for k in (
        "term_id", "registered_term", "term_type", "disease_id",
        "start", "end", "matched_text", "token_start_index", "token_end_index",
    ))


def main():
    parser = argparse.ArgumentParser(description="저장된 문맥 판정의 키워드 후보 연결 비교")
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--diseases", type=Path, required=True)
    parser.add_argument("--keywords", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")
    diseases = [json.loads(line) for line in args.diseases.read_text(encoding="utf-8").splitlines() if line.strip()]
    keywords = [json.loads(line) for line in args.keywords.read_text(encoding="utf-8").splitlines() if line.strip()]
    names = {row["DIS_UNIQN"]: row["ATT_DIS_NM"] for row in diseases}
    registry = {row["term_id"]: row for row in keywords}
    if len(names) != len(diseases) or len(registry) != len(keywords):
        raise ValueError("병증 또는 키워드 식별번호가 중복됐습니다.")
    if policy.MAX_KEYWORD_CANDIDATES != legacy_search.MAX_KEYWORD_CANDIDATES:
        raise ValueError("비교 대상의 키워드 후보 상한이 다릅니다.")
    records, inputs, seen = [], [], set()
    for report_path in args.reports:
        source = read_json(report_path)
        if (source["settings"]["prompt_version"] != "mention_context_two_stage_kiwi_context_v3"
                or source["model"]["name"] != "gemma4:e4b"
                or source["used_in_search"] is not False
                or source["criteria_used_for_inference"] is not False):
            raise ValueError("이번 실험은 저장된 Gemma 문맥 v3 개발 결과만 사용합니다.")
        matches = read_verified(source["source_match_report"])
        if matches["match_policy_version"] != "normalized_unit_occurrences_v1":
            raise ValueError("표현 일치 정책이 다릅니다.")
        if fingerprint(args.diseases)["sha256"] != matches["disease_source"]["sha256"]:
            raise ValueError("병증 원문 버전이 다릅니다.")
        analysis = read_verified(matches["source_analysis"])
        if not any(ref["sha256"] == fingerprint(args.keywords)["sha256"] for ref in analysis["inputs"]):
            raise ValueError("등록 키워드 버전이 다릅니다.")
        original_cases = {row["case_id"]: row for row in matches["cases"]}
        if len(original_cases) != len(matches["cases"]):
            raise ValueError("원본 사례 식별번호가 중복됐습니다.")
        inputs.append({"report": fingerprint(report_path), "source_match_report": source["source_match_report"], "model": source["model"], "prompt_version": source["settings"]["prompt_version"]})
        for case in source["cases"]:
            if case["case_id"] in seen:
                raise ValueError("입력 보고서 사이에 사례 식별번호가 중복됐습니다.")
            seen.add(case["case_id"])
            original = original_cases[case["case_id"]]
            if (case["input_text"] != original["input_text"]
                    or Counter(map(link_identity, case["keyword_matches"])) != Counter(map(link_identity, original["keyword_matches"]))):
                raise ValueError("문맥 판정에 대응하는 원문·키워드 연결이 다릅니다.")
            for link in case["keyword_matches"]:
                item = registry[link["term_id"]]
                if (link["registered_term"], link["term_type"], link["disease_id"]) != (item["term"].strip(), item["term_type"], item["DIS_UNIQN"]):
                    raise ValueError("저장된 연결과 현재 등록 자료가 다릅니다.")
            result = policy.partition_context_case(case, names)
            result["legacyKeywordIds"] = legacy_search.search_keywords(case["input_text"], diseases, keywords)
            result["source_report"] = str(report_path.resolve())
            records.append(result)
            print(case["case_id"], "기존", len(result["legacyKeywordIds"]), "정규화만", len(result["normalizedKeywordIds"]), "문맥 반영", len(result["contextKeywordIds"]), "검토 후보", len(result["reviewKeywordIds"]), flush=True)
    span_counts, link_counts = Counter(), Counter()
    for case in records:
        span_counts.update(case["summary"]["span_policy_counts"])
        link_counts.update(case["summary"]["link_policy_counts"])
    report = {
        "report_version": "context_keyword_candidate_bridge_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": policy.POLICY_VERSION,
        "used_in_search": False, "semantic_search_executed": False,
        "rrf_applied": False, "live_model_calls": 0, "criteria_used_for_inference": False,
        "temporality_evaluated": False,
        "sources": inputs, "disease_source": fingerprint(args.diseases),
        "keyword_source": fingerprint(args.keywords),
        "script": fingerprint(__file__), "policy_script": fingerprint(policy.__file__),
        "legacy_search_script": fingerprint(legacy_search.__file__),
        "legacy_keyword_rules_script": fingerprint(keyword_rules.__file__),
        "notes": [
            "기존 방식, 정규화만 적용, 정규화와 문맥 적용의 키워드 후보를 비교한다. 후보는 병증명·ID순이며 관련도 순위가 아니다.",
            "부정은 해당 표현의 키워드 지지만 제외한다. 병증 전체를 제외하지 않으며 다른 긍정 표현의 지지는 유지한다.",
            "불확실·미판정은 검토 대상으로 분리하며 이 실험의 긍정 키워드 지지에는 포함하지 않는다.",
            "긍정은 과거 언급도 포함한 기존 분류다. 현재 증상이나 임상 판단의 확정을 뜻하지 않는다.",
            "의미 검색·RRF·검색 API·기존 순위에는 미반영이다. 검색 정확도 개선을 입증하는 결과가 아니다.",
        ],
        "summary": {
            "cases": len(records), "classified_spans": sum(c["summary"]["spans"] for c in records),
            "mapped_links": sum(c["summary"]["links"] for c in records),
            "span_policy_counts": dict(span_counts), "link_policy_counts": dict(link_counts),
            "cases_changed_by_normalization": sum(c["legacyKeywordIds"] != c["normalizedKeywordIds"] for c in records),
            "cases_changed_by_context": sum(c["normalizedKeywordIds"] != c["contextKeywordIds"] for c in records),
            "cases_with_review_spans": sum(any(m["candidate_policy_status"].startswith("REVIEW_") for m in c["mentions"]) for c in records),
        },
        "cases": records,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(serialized)
    if read_json(args.output) != report:
        raise ValueError("저장 결과와 메모리의 결과가 다릅니다.")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("저장 완료:", args.output)
    print("LLM 재실행 없음 / 키워드 후보 비교만 수행 / 기존 순위 변경 없음")


if __name__ == "__main__":
    main()
