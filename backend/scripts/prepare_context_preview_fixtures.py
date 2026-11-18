"""저장된 실험 결과로 화면 개발용 응답 예제를 만든다. DB·모델·네트워크는 사용하지 않는다."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SCENARIOS = [
    ("positive", "후보 검토", "context_live_preview_01.json", "CANDIDATE_REVIEW"),
    ("negative", "증상 부정", "context_live_negative_01.json", "REVIEW_INPUT"),
    ("uncertain", "존재 여부 불확실", "context_live_uncertain_01.json", "CONFIRM_INTERPRETATION"),
    ("word", "문서 속 단어 언급", "context_live_word_01.json", "REVIEW_INPUT"),
]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), digest(raw)


def save_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    saved, sha = read_json(path)
    if saved != value:
        raise ValueError("저장 후 다시 읽은 내용이 다릅니다: " + path.name)
    return sha


def prepare(experiment_root, output_dir):
    if output_dir.exists():
        raise FileExistsError("기존 파일을 보존하기 위해 중단합니다. 새 출력 폴더를 지정해주세요: " + str(output_dir))
    prepared = []
    for key, label, filename, route in SCENARIOS:
        path = experiment_root / filename
        source, sha = read_json(path)
        if source.get("status") != "COMPLETED" or source.get("route") != route:
            raise ValueError("완료 상태 또는 예상 분기가 다릅니다: " + filename)
        symptoms = source.get("symptoms")
        message = source.get("message")
        candidates = source.get("candidates")
        review = source.get("reviewMentions")
        if not isinstance(symptoms, str) or not symptoms.strip() or not isinstance(message, str):
            raise ValueError("입력 문장 또는 안내 문구가 없습니다: " + filename)
        if not isinstance(candidates, list) or not isinstance(review, list):
            raise ValueError("후보 또는 검토 표현 목록이 없습니다: " + filename)
        if route != "CANDIDATE_REVIEW" and candidates:
            raise ValueError("확인 경로에 검색 후보가 포함됐습니다: " + filename)
        if route == "CANDIDATE_REVIEW" and not candidates:
            raise ValueError("후보 검토 경로에 검색 후보가 없습니다: " + filename)
        for rank, candidate in enumerate(candidates, 1):
            if candidate.get("rank") != rank or type(candidate.get("id")) is not int:
                raise ValueError("후보 식별번호 또는 순서가 올바르지 않습니다: " + filename)
            if not isinstance(candidate.get("keywordEvidence"), list) or "semanticEvidence" not in candidate:
                raise ValueError("후보 근거 필드가 없습니다: " + filename)
            if candidate["semanticEvidence"] is not None and not isinstance(candidate["semanticEvidence"], dict):
                raise ValueError("의미 검색 근거 형식이 다릅니다: " + filename)
        if route == "CONFIRM_INTERPRETATION" and not review:
            raise ValueError("확인할 증상 표현이 없습니다: " + filename)
        for mention in review:
            start, end = mention.get("start"), mention.get("end")
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(symptoms):
                raise ValueError("검토 표현의 원문 범위가 잘못됐습니다: " + filename)
            if symptoms[start:end] != mention.get("source_text"):
                raise ValueError("검토 표현과 원문이 다릅니다: " + filename)
        # 1은 화면 개발 전용 가상 상담 ID이며, 실제 서비스 요청에 사용하지 않는다.
        body = {
            "caseId": 1, "previewId": "fixture-preview-" + key,
            "symptoms": symptoms, "route": route, "message": message,
            "total": len(candidates), "candidates": candidates,
            "reviewMentions": review, "explanationStatus": "NOT_REQUESTED",
            "historySaved": False,
        }
        prepared.append((key, label, path, sha, body))

    # 읽기 단계가 끝난 뒤에만 새 폴더를 만든다. 기존 결과 파일에는 쓰지 않는다.
    output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for key, label, source_path, sha, body in prepared:
        filename = key + ".json"
        output_sha = save_new(output_dir / filename, body)
        if digest(source_path.read_bytes()) != sha:
            raise ValueError("작업 중 원본 결과가 변경됐습니다: " + source_path.name)
        records.append({
            "key": key, "label": label, "file": filename,
            "route": body["route"], "total": body["total"],
            "review_mentions": len(body["reviewMentions"]),
            "source_file": source_path.name, "source_sha256": sha,
            "response_sha256": output_sha,
        })
        print(key, body["route"], "후보", body["total"], "검토 표현", len(body["reviewMentions"]), flush=True)

    manifest = {
        "fixture_version": "consultation_preview_ui_fixture_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_only": True,
        "synthetic_case_id": 1,
        "synthetic_ids_must_not_be_sent_to_service": True,
        "source_results_unchanged": True,
        "candidate_order_and_evidence_preserved": True,
        "real_db_calls": 0, "real_model_calls": 0, "network_calls": 0,
        "scenarios": records,
        "display_rules": {
            "CANDIDATE_REVIEW": "상위 3개를 먼저 표시하고 더보기로 전체 후보와 근거를 확인한다. 확정 진단으로 표시하지 않는다.",
            "CONFIRM_INTERPRETATION": "검색 후보 대신 message와 reviewMentions의 원문을 표시하여 증상의 의미나 존재 여부를 확인한다.",
            "REVIEW_INPUT": "검색 후보 대신 message를 표시하여 입력을 확인한다. 환자에게 증상이 없다고 단정하지 않는다.",
        },
        "integration_notes": [
            "예제 응답은 서버를 호출하지 않고 화면에만 주입한다.",
            "previewId는 검색 이력 ID가 아니다. diseaseSearchId에 넣지 않는다.",
            "historySaved=false인 상태를 유지하고 예제 결과로 상담을 저장하지 않는다.",
            "실제 로그인·상담 접근 검증과 main.py·상담 화면 연결은 별도로 진행한다.",
            "근거 없는 후보가 섞일 수 있으므로 후보 수나 순위 변화를 정확도 향상으로 해석하지 않는다.",
        ],
    }
    save_new(output_dir / "index.json", manifest)
    print("화면 예제 4건 저장·재조회 확인 완료:", output_dir)
    print("원본 결과 보존 / DB·모델·네트워크 호출: 0 / 실제 서비스 연결: 미실행")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=Path(r"C:\km-cdss-data\실험자료\문맥추가검증_v1"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.experiment_root, args.output_dir)


if __name__ == "__main__":
    main()
