"""설치된 두 모델에 같은 증상 존재 판정 요청을 보내는 개발 진단."""
import argparse
import copy
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.ai import context_classification_two_stage as classifier


def fingerprint(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description="설치된 모델의 증상 존재 판정 대조 진단")
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--comparison-model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")
    source = json.loads(args.source_report.read_text(encoding="utf-8"))
    if source["settings"]["think"] is not False:
        raise ValueError("사고 모드가 꺼진 원본 보고서를 사용해주세요.")
    if fingerprint(classifier.__file__)["sha256"] != source["classifier_script"]["sha256"]:
        raise ValueError("현재 분류 코드가 원본 보고서 실행 당시와 다릅니다.")
    cases = [row for row in source["cases"] if row["case_id"] == args.case_id]
    if len(cases) != 1:
        raise ValueError("진단할 사례를 하나로 선택할 수 없습니다.")
    case = cases[0]
    stages = [row for row in case.get("raw_response", {}).get("stages", []) if row["stage"] == "assertion"]
    if len(stages) != 1:
        raise ValueError("원본 보고서에 증상 존재 판단 단계가 없습니다.")
    supplied = stages[0]["model_input"]
    if supplied["input_text"] != case["input_text"]:
        raise ValueError("단계 입력과 사례 원문이 다릅니다.")
    if not supplied["mentions"]:
        raise ValueError("진단할 표현이 없습니다.")
    for mention in supplied["mentions"]:
        start, end = mention["start"], mention["end"]
        if not 0 <= start < end <= len(case["input_text"]) or case["input_text"][start:end] != mention["matched_text"]:
            raise ValueError("진단 대상 위치가 원문과 다릅니다.")

    # 양쪽 요청 모두에 같은 출력 구조 안내를 제공해 정보 차이를 줄인다.
    system_prompt = source["settings"]["stage_prompts"]["assertion"] + (
        "\n출력은 decisions 배열을 가진 JSON 객체다. 각 항목은 mention_id와 assertion만 가진다. "
        "입력의 모든 mention_id를 한 번씩 포함한다. assertion은 AFFIRMED, NEGATED, UNCERTAIN, UNASSESSED 중 하나다."
    )
    user_text = json.dumps(supplied, ensure_ascii=False)
    if len((system_prompt + user_text).encode("utf-8")) + 512 > 3072:
        raise ValueError("진단 입력의 보수적 크기 한도를 초과했습니다.")
    base_url = source["settings"]["base_url"]
    model = source["model"]["name"]
    if model != "qwen3.5:4b":
        raise ValueError("이번 진단은 기존 qwen3.5:4b 모델로 제한합니다.")
    options = copy.deepcopy(source["settings"]["options"])
    tags = classifier.ollama_json(base_url, "/api/tags")
    selected = next((row for row in tags["models"] if row["name"] == model), None)
    if selected is None or selected.get("digest") != source["model"].get("digest"):
        raise ValueError("설치 모델이 원본 보고서와 다릅니다.")
    if args.comparison_model == model:
        parser.error("비교 모델은 기존 모델과 달라야 합니다.")
    candidate = next((row for row in tags["models"] if row["name"] == args.comparison_model), None)
    if candidate is None:
        raise ValueError("비교 모델이 설치 목록에 없습니다. 자동 다운로드는 하지 않습니다.")
    model_details = {}
    for row in (selected, candidate):
        details = classifier.ollama_json(base_url, "/api/show", {"model": row["name"]})
        if "completion" not in details.get("capabilities", []) or False not in details.get("thinking", {}).get("values", []):
            raise ValueError("모델의 생성 기능 또는 사고 모드 끄기 지원을 확인하지 못했습니다.")
        model_details[row["name"]] = {
            key: details.get(key) for key in ("details", "parameters", "thinking", "capabilities")
        }
    server = classifier.ollama_json(base_url, "/api/version")
    base_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "stream": False, "think": False, "keep_alive": "5m", "options": options,
    }
    schema = classifier.response_schema(classifier.AssertionResponse, supplied["mentions"])
    report = {
        "report_version": "assertion_model_comparison_probe_v1",
        "purpose": "같은 요청을 설치된 두 모델에 전달하는 개발 진단. 한 문장 비교이며 의미 검토 전.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "used_in_search": False, "semantic_review_status": "NOT_REVIEWED",
        "criteria_used_for_inference": False,
        "source_report": fingerprint(args.source_report),
        "script": fingerprint(__file__),
        "classifier_script": fingerprint(classifier.__file__),
        "utility_script": fingerprint(classifier.helpers.__file__),
        "case_id": args.case_id, "input_text": case["input_text"],
        "models": [selected, candidate], "model_details": model_details, "server_version": server["version"],
        "settings": {
            "base_url": base_url, "system_prompt": system_prompt, "model_input": supplied,
            "options": options, "think": False, "automatic_retries": 0,
            "comparison_total_timeout_seconds": 120,
            "per_model_timeout_seconds": 60,
            "changed_request_field": "model",
            "explicit_options_identical": True,
            "family_defaults_recorded_per_model": True,
            "source_prompt_modified_equally_for_both_models": True,
            "response_schema": schema,
        },
        "probes": [
            {"mode": "reference", "model": model, "status": "NOT_RUN"},
            {"mode": "candidate", "model": candidate["name"], "status": "NOT_RUN"},
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        def save_progress():
            text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
            stream.seek(0)
            stream.write(text + "\n")
            stream.truncate()
            stream.flush()

        save_progress()
        deadline = time.monotonic() + 120
        try:
            for record in report["probes"]:
                payload = copy.deepcopy(base_payload)
                payload["model"] = record["model"]
                payload["format"] = schema
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    record.update(status="NOT_RUN", error="대조 실험 제한시간이 끝났습니다.")
                    break
                started = time.monotonic()
                record["status"] = "RUNNING"
                save_progress()
                print(record["mode"], record["model"], "분석 중", flush=True)
                try:
                    raw = classifier.ollama_json(base_url, "/api/chat", payload, timeout=min(60, remaining))
                except (OSError, ValueError) as error:
                    record.update(status="INCOMPLETE", error=f"통신 실패: {error}", elapsed_seconds=time.monotonic() - started)
                    save_progress()
                    break
                record.update(raw_response=raw, elapsed_seconds=time.monotonic() - started)
                try:
                    if time.monotonic() > deadline or record["elapsed_seconds"] > 60 or raw.get("done") is not True:
                        raise ValueError("제한시간 또는 완료 상태를 확인해주세요.")
                    if raw.get("model") != record["model"]:
                        raise ValueError("응답 모델 이름이 요청한 모델과 다릅니다.")
                    if raw.get("done_reason") != "stop":
                        raise ValueError(f"응답 미완료: {raw.get('done_reason')}")
                    if raw["prompt_eval_count"] > 3072 or raw["eval_count"] > options["num_predict"]:
                        raise ValueError("입력·출력 토큰 한도를 초과했습니다.")
                    if raw.get("message", {}).get("thinking"):
                        raise ValueError("사고 모드가 꺼지지 않았습니다.")
                    decisions = classifier.validate_stage(classifier.AssertionResponse, supplied["mentions"], raw["message"]["content"])
                except (ValueError, KeyError, TypeError) as error:
                    record.update(status="FINAL_NOT_VALIDATED", validation_error=str(error))
                else:
                    record.update(status="STRUCTURE_VALID", decisions=decisions)
                print(record["mode"], record["status"], record.get("decisions", []), flush=True)
                save_progress()
                if time.monotonic() > deadline or raw.get("done") is not True:
                    break
        except KeyboardInterrupt:
            report["interrupted"] = True
            if record["status"] == "RUNNING":
                record.update(status="INCOMPLETE", error="사용자가 요청 중 실행을 중단했습니다.")
            print("중단까지의 진단 결과를 저장합니다.")
        finally:
            save_progress()
    if json.loads(args.output.read_text(encoding="utf-8")) != report:
        raise ValueError("저장한 진단 결과가 일치하지 않습니다.")
    print("저장 완료:", args.output)
    print("의미 정확성 검토 전 / 기존 검색 반영 없음")
    if any(record["status"] != "STRUCTURE_VALID" for record in report["probes"]):
        print("원본 응답을 보존했습니다. 형식 검사 결과와 의미 판정을 구분해 검토해주세요.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
