"""저장된 검색 결과의 후보 검토·입력 확인 경로 비교. 실제 API는 변경하지 않는다."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

POLICY_VERSION = "candidate_review_or_input_confirmation_v1"


def fingerprint(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_verified(ref):
    if fingerprint(ref["path"])["sha256"] != ref["sha256"]:
        raise ValueError(f"참조 파일이 저장 이후 변경됐습니다: {ref['path']}")
    return json.loads(Path(ref["path"]).read_text(encoding="utf-8"))


def route_case(hybrid, bridge):
    if (hybrid["status"] != "COMPLETED"
            or hybrid["case_id"] != bridge["case_id"]
            or hybrid["input_text"] != bridge["input_text"]):
        raise ValueError("순위 비교와 후보 연결의 사례가 다르거나 미완료입니다.")
    known = {"ACCEPT_KEYWORD_SUPPORT", "IGNORE_NEGATED_SUPPORT", "IGNORE_BODY_SITE",
             "IGNORE_NON_SYMPTOM", "REVIEW_ASSERTION", "REVIEW_CONTEXT"}
    if any(m["candidate_policy_status"] not in known for m in bridge["mentions"]):
        raise ValueError("알 수 없는 후보 처리 상태입니다.")
    positives = [m for m in bridge["mentions"] if m["candidate_policy_status"] == "ACCEPT_KEYWORD_SUPPORT"]
    reviews = [m for m in bridge["mentions"] if m["candidate_policy_status"].startswith("REVIEW_")]
    if bool(positives) != bool(bridge["contextKeywordIds"]):
        raise ValueError("긍정 표현과 키워드 후보 유무가 다릅니다.")
    if bool(positives) != hybrid["hasAffirmedKeywordSupport"] or reviews != hybrid["reviewMentions"]:
        raise ValueError("후보 연결과 순위 비교의 검토 대상이 다릅니다.")
    for mention in bridge["mentions"]:
        if bridge["input_text"][mention["start"]:mention["end"]] != mention["source_text"]:
            raise ValueError("검토 표현의 원문 위치가 다릅니다.")
    if reviews:
        route = "CONFIRM_INTERPRETATION"
        reason = "UNCERTAIN_OR_UNASSESSED_MATCHED_EXPRESSION"
        message = "증상 표현의 의미나 존재 여부를 확인해주세요."
    elif not positives:
        route = "REVIEW_INPUT"
        reason = "NO_AFFIRMED_MATCHED_SYMPTOM"
        message = "현재 분석 범위에서 후보 검토에 사용할 증상을 확인하기 어렵습니다. 증상 표현을 확인해주세요."
    else:
        route = "CANDIDATE_REVIEW"
        reason = "AFFIRMED_MATCHED_EXPRESSION_AVAILABLE"
        message = "분석된 증상 표현과 검색 후보의 근거를 함께 검토해주세요."
    diagnostic = hybrid["variants"]["context"]["candidates"]
    proposed = diagnostic if route == "CANDIDATE_REVIEW" else []
    return {
        "case_id": hybrid["case_id"], "input_text": hybrid["input_text"],
        "proposedRoute": route, "reason": reason, "message": message,
        "affirmedMentions": positives, "reviewMentions": reviews,
        "diagnosticCandidates": diagnostic,
        "proposedCandidates": proposed, "proposedTop3": proposed[:3],
        "automaticDisplayDeferred": route != "CANDIDATE_REVIEW",
        "diagnosticTop3WithoutAffirmedKeywordSupport": hybrid["contextTop3WithoutAffirmedKeywordSupport"],
    }


def main():
    parser = argparse.ArgumentParser(description="문맥 기반 검색의 후보 검토·입력 확인 경로 비교")
    parser.add_argument("--hybrid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")
    source = json.loads(args.hybrid.read_text(encoding="utf-8"))
    if source["report_version"] != "context_hybrid_shadow_v1" or source["used_in_search"] is not False:
        raise ValueError("문맥·의미 검색 결합 비교 결과를 사용해주세요.")
    if any(c["status"] != "COMPLETED" for c in source["cases"]):
        raise ValueError("순위 비교의 모든 사례를 완료한 뒤 진행해주세요.")
    bridge = read_verified(source["source_candidates"])
    if bridge["report_version"] != "context_keyword_candidate_bridge_v1" or bridge["used_in_search"] is not False:
        raise ValueError("후보 연결 결과 형식이 다릅니다.")
    for key in ["script", "search_script", "embedding_script"]:
        read_path = source[key]
        if fingerprint(read_path["path"])["sha256"] != read_path["sha256"]:
            raise ValueError("순위 비교를 실행했던 코드가 변경됐습니다.")
    for ref in source["data"].values():
        if fingerprint(ref["path"])["sha256"] != ref["sha256"]:
            raise ValueError("순위 비교에 사용한 자료가 변경됐습니다.")
    originals = {c["case_id"]: c for c in bridge["cases"]}
    if (len(originals) != len(bridge["cases"])
            or len({c["case_id"] for c in source["cases"]}) != len(source["cases"])
            or set(originals) != {c["case_id"] for c in source["cases"]}):
        raise ValueError("후보 연결과 순위 비교의 사례 범위가 다릅니다.")
    records = [route_case(c, originals[c["case_id"]]) for c in source["cases"]]
    for case in records:
        print(case["case_id"], case["proposedRoute"], "기록 후보", len(case["diagnosticCandidates"]),
              "검토 표시 후보", len(case["proposedCandidates"]), flush=True)
    report = {
        "report_version": "context_search_routing_experiment_v1", "policy_version": POLICY_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_hybrid": fingerprint(args.hybrid), "source_candidates": source["source_candidates"],
        "script": fingerprint(__file__), "used_in_search": False,
        "model_calls": 0, "query_embedding_calls": 0, "ranks_recomputed": False,
        "is_final_recommendation": False, "temporality_evaluated": False,
        "notes": [
            "실제 API나 화면에 적용하지 않은 후보 표시 정책 제안이다. 기존 검색 순위는 모두 진단용 기록으로 보존한다.",
            "긍정으로 분류된 등록 표현을 못 찾았다는 것은 환자에게 증상이 없다는 뜻이 아니다. 등록되지 않은 표현도 있어 입력 검토로 보낸다.",
            "불확실·미판정이 있으면 다른 긍정 표현이 있어도 이번 정책은 입력 해석 확인을 먼저 제안한다.",
            "후보 검토 경로는 검색 정답이나 현재 증상의 확정이 아니다. 과거·현재 구분과 후보별 근거 검증은 추가 작업이다.",
            "후보를 숨긴 수나 경로 분리 수는 검색 정확도 개선을 뜻하지 않는다.",
        ],
        "summary": {
            "cases": len(records), "route_counts": dict(Counter(c["proposedRoute"] for c in records)),
            "automatic_display_deferred_cases": sum(c["automaticDisplayDeferred"] for c in records),
            "cases_diagnostic_candidates_preserved": sum(bool(c["diagnosticCandidates"]) for c in records),
            "cases_top3_order_preserved_when_shown": sum(c["proposedRoute"] == "CANDIDATE_REVIEW" and c["proposedTop3"] == c["diagnosticCandidates"][:3] for c in records),
            "quality_evaluation": "NOT_EVALUATED_NO_DISEASE_GOLD",
        },
        "cases": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if json.loads(args.output.read_text(encoding="utf-8")) != report:
        raise ValueError("저장한 경로 비교 결과가 다릅니다.")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("저장 완료:", args.output)
    print("모델 재실행 없음 / 기존 순위 기록 보존 / 실제 API·화면 반영 없음")


if __name__ == "__main__":
    main()
