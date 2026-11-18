import argparse
import hashlib
import json
from importlib.metadata import version
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.ai import context_classification_two_stage as context_classification
from backend.ai.context_classification_two_stage import (
    PROMPT_VERSION, OPTIONS, STAGE_PROMPTS, THINKING_ENABLED, ContextRunError,
    classify_case, model_input, ollama_json, prepare_mentions,
)


def fingerprint(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def update_summary(report: dict) -> None:
    cases = report["cases"]
    valid = [case for case in cases if case["status"] == "STRUCTURE_VALID"]
    decisions = [item for case in valid for item in case["mentions"]]
    report["summary"] = {
        "selected_cases": len(cases),
        "structure_valid_cases": len(valid),
        "incomplete_cases": sum(case["status"] == "INCOMPLETE" for case in cases),
        "not_run_cases": sum(case["status"] == "NOT_RUN" for case in cases),
        "classified_spans": len(decisions),
        "mapped_keyword_matches": sum(len(case["keyword_matches"]) for case in valid),
        "assertion_counts": dict(Counter(item["assertion"] for item in decisions)),
        "context_counts": dict(Counter(item["context"] for item in decisions)),
        "human_semantically_reviewed_cases": 0,
        "attempted_model_calls": sum(
            len((case.get("raw_response") or {}).get("stages", [])) for case in cases
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 문맥 요청을 고정한 Qwen/Gemma 모델 비교")
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:4b", choices=["qwen3.5:4b", "gemma4:e4b"])
    parser.add_argument("--case-id")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    # 비교 기준과 다른 문맥 요청으로 모델을 실행하는 것을 방지한다.
    expected_classifier_sha256 = "0769abbd290a00037e2ce43704b3a9f4b90e07a9befd4d671f95f33885c55632"
    if fingerprint(Path(context_classification.__file__))["sha256"] != expected_classifier_sha256:
        parser.error("모델 비교 전에 제공된 이전 문맥 파일로 복원해주세요. 기준 파일과 다릅니다.")
    if PROMPT_VERSION != "mention_context_two_stage_kiwi_v1":
        parser.error("이전 문맥 요청 버전으로 복원됐는지 확인해주세요.")
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")

    source = json.loads(args.matches.read_text(encoding="utf-8"))
    if source["match_policy_version"] != "normalized_unit_occurrences_v1":
        raise ValueError("이번 문맥 검사와 다른 표현 일치 정책입니다.")
    cases = source["cases"]
    if args.case_id is not None:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            parser.error("선택한 사례 식별번호가 입력 자료에 없습니다.")
    if args.limit is not None:
        if not 1 <= args.limit <= len(cases):
            raise ValueError("실행 건수는 1 이상 전체 사례 수 이하여야 합니다.")
        cases = cases[:args.limit]
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("사례 식별번호가 중복됐습니다.")
    prepared = [(case, prepare_mentions(case)) for case in cases]
    if any(not mentions for case, mentions in prepared):
        raise ValueError("일치 후보가 없는 사례는 별도 무후보 실험으로 구분해주세요.")

    tags = ollama_json(args.base_url, "/api/tags")
    selected_model = next(
        (row for row in tags["models"] if row["name"] == args.model), None
    )
    if selected_model is None:
        raise ValueError("선택한 모델이 로컬 Ollama에 없습니다.")
    server = ollama_json(args.base_url, "/api/version")
    details = ollama_json(args.base_url, "/api/show", {"model": args.model})
    if "completion" not in details.get("capabilities", []):
        raise ValueError("문장 생성 기능이 없는 모델입니다.")
    if THINKING_ENABLED not in details.get("thinking", {}).get("values", []):
        raise ValueError("선택한 사고 모드 지원 여부를 확인하지 못했습니다.")

    report = {
        "report_version": "context_two_stage_morphology_experiment_v1",
        "purpose": "이전 문맥 요청·입력·설정을 고정한 모델 비교. 문맥과 존재 판정 모두 선택 모델을 새로 호출함. 의미 검토 전.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "criteria_used_for_inference": False,
        "used_in_search": False,
        "source_match_report": fingerprint(args.matches),
        "script": fingerprint(Path(__file__)),
        "classifier_script": fingerprint(Path(context_classification.__file__)),
        "utility_script": fingerprint(Path(context_classification.helpers.__file__)),
        "morphology_script": fingerprint(Path(context_classification.morphology_helpers.__file__)),
        "model": selected_model,
        "server_version": server["version"],
        "model_details": {
            "details": details.get("details"),
            "thinking": details.get("thinking"),
            "parameters": details.get("parameters"),
        },
        "settings": {
            "base_url": args.base_url,
            "prompt_version": PROMPT_VERSION,
            "schema_version": context_classification.SCHEMA_VERSION,
            "assertion_input_policy": context_classification.MORPHOLOGY_INPUT_POLICY,
            "morphology_version": version("kiwipiepy"),
            "morphology_policy": context_classification.morphology_helpers.POLICY_VERSION,
            "morphology_settings": context_classification.morphology_helpers.KIWI_SETTINGS,
            "model_output_fields": {
                "context": ["mention_id", "context"],
                "assertion": ["mention_id", "assertion"],
            },
            "second_stage_target_rule": "context == PATIENT_SYMPTOM",
            "raw_response_layout": "stages[].raw_response",
            "selected_case_id": args.case_id,
            "temporality_requested": False,
            "reason_requested": False,
            "source_text_origin": "INPUT_SPAN_COPY",
            "stage_prompts": STAGE_PROMPTS,
            "options": OPTIONS,
            "think": THINKING_ENABLED,
            "stream": False,
            "case_total_timeout_seconds": 60,
            "maximum_model_calls_per_case": 2,
            "automatic_retries": 0,
            "max_input_tokens": 3072,
            "input_guard": "utf8_content_bytes_plus_512_then_server_count",
            "max_output_tokens_per_call": OPTIONS["num_predict"],
            "source_case_count": len(source["cases"]),
            "same_span_links_grouped": True,
            "validation_scope": [
                "json_schema", "mention_id_coverage",
                "source_match_positions", "stage_specific_id_coverage",
                "non_symptom_assertion_policy",
            ],
        },
        "cases": [
            {
                "case_id": case["case_id"],
                "input_text": case["input_text"],
                "status": "NOT_RUN",
                "model_input": model_input(case, mentions),
                "semantic_review_status": "NOT_REVIEWED",
                "used_in_search": False,
            }
            for case, mentions in prepared
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        def save_progress():
            update_summary(report)
            text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
            file.seek(0)
            file.write(text + "\n")
            file.truncate()
            file.flush()

        save_progress()
        try:
            for number, (case, mentions) in enumerate(prepared):
                print(
                    f"[{number + 1}/{len(prepared)}] {case['case_id']} 분석 중",
                    flush=True,
                )
                record = report["cases"][number]
                try:
                    record.update(classify_case(
                        case, mentions, args.base_url, args.model
                    ))
                except ContextRunError as error:
                    record.update({
                        "status": "INCOMPLETE",
                        "error": str(error),
                        "raw_response": error.raw_response,
                    })
                    save_progress()
                    print("미완료:", str(error), flush=True)
                    if error.stop_suite:
                        print("호출 종료가 불확실해 후속 요청을 중단합니다.", flush=True)
                        break
                except KeyboardInterrupt:
                    record.update({
                        "status": "INCOMPLETE", "error": "사용자가 실행을 중단했습니다."
                    })
                    print("중단까지의 결과를 저장합니다.", flush=True)
                    break
                else:
                    labels = [
                        f"{item['mention_id']}:{item['context']}/{item['assertion']}"
                        for item in record["mentions"]
                    ]
                    print("형식 검사 통과 / 의미 검토 전:", labels, flush=True)
                save_progress()
        finally:
            save_progress()

    saved = json.loads(args.output.read_text(encoding="utf-8"))
    if saved != report:
        raise ValueError("저장한 문맥 판정 결과가 일치하지 않습니다.")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("저장 완료:", args.output)
    print("기존 검색 순위 반영: 미실행 / 사람의 의미 검토: 미실행")
    if report["summary"]["structure_valid_cases"] != len(prepared):
        print("미완료 또는 미실행 사례가 있습니다. 결과 파일을 확인해주세요.")
        raise SystemExit(1)
    print("문맥 판단 실험 저장·재조회 확인 완료")


if __name__ == "__main__":
    main()

