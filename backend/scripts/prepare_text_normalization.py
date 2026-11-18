import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def json_bytes(value) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, indent=2, allow_nan=False
    ) + "\n").encode("utf-8")


def jsonl_bytes(rows) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
        for row in rows
    ).encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="표현 정규화 실험 준비")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise ValueError("실험 폴더가 이미 있습니다. 새 폴더명을 사용해주세요.")

    # 검색용 표현 사전이 아닌 개발 검사 문장과 판정 초안이다.
    cases = [
        ("NORM-001", "inflection", "bloating", "배가 더부룩했어요.", [("더부룩함", "affirmed")]),
        ("NORM-002", "inflection", "bloating", "속이 더부룩하네요.", [("더부룩함", "affirmed")]),
        ("NORM-003", "inflection", "tightness", "가슴이 답답했어요.", [("답답함", "affirmed")]),
        ("NORM-004", "inflection", "tightness", "가슴이 답답하네요.", [("답답함", "affirmed")]),
        ("NORM-005", "negation", "tightness", "답답하지 않아요.", [("답답함", "negated")]),
        ("NORM-006", "negation", "tightness", "안 답답해요.", [("답답함", "negated")]),
        ("NORM-007", "mixed_symptoms", "cough_bloating", "기침은 없고 배가 더부룩해요.", [("기침", "negated"), ("더부룩함", "affirmed")]),
        ("NORM-008", "degree_negation", "cough", "기침이 심하지는 않아요.", [("기침", "affirmed")]),
        ("NORM-009", "negation", "vomiting", "구토를 하지 않아요.", [("구토", "negated")]),
        ("NORM-010", "multiple_symptoms", "headache_cough", "두통이 있고 기침도 나요.", [("두통", "affirmed"), ("기침", "affirmed")]),
        ("NORM-011", "non_symptom_context", "tightness", "회의가 답답하게 진행됐어요.", [("답답함", "not_symptom")]),
        ("NORM-012", "uncertainty", "cough", "기침이 있는지 잘 모르겠어요.", [("기침", "uncertain")]),
    ]

    queries = [
        {"case_id": case_id, "input_text": text}
        for case_id, category, group_id, text, mentions in cases
    ]
    criteria = [
        {
            "case_id": case_id,
            "category": category,
            "group_id": group_id,
            "review_status": "draft",
            "expected_mentions": [
                {"registered_term": term, "assertion": assertion}
                for term, assertion in mentions
            ],
        }
        for case_id, category, group_id, text, mentions in cases
    ]

    sources = [
        (args.project_root, "backend/ai/keyword_rules.py"),
        (args.project_root, "backend/ai/search.py"),
        (args.project_root, "backend/ai/prescription_search.py"),
        (args.project_root, "backend/ai/embedding.py"),
        (args.data_root, "검증결과/개발대조_키워드일치내역_01.json"),
        (args.data_root, "검증결과/개발대조_처방검색기준결과_01.json"),
    ]

    payloads = {
        "queries.jsonl": jsonl_bytes(queries),
        "criteria.jsonl": jsonl_bytes(criteria),
    }
    baselines = []
    for base, relative in sources:
        source = base / relative
        content = source.read_bytes()
        snapshot = "baseline/" + relative
        payloads[snapshot] = content
        baselines.append({
            "original_path": str(source.resolve()),
            "snapshot_path": snapshot,
            "sha256": hashlib.sha256(content).hexdigest(),
        })

    payloads["manifest.json"] = json_bytes({
        "experiment_version": "text_normalization_dev_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "개발용 회귀 검사 준비. 독립 최종 평가 또는 임상 정답이 아님.",
        "label_review_status": "draft",
        "case_count": len(queries),
        "assertion_definition": {
            "affirmed": "증상이 긍정적으로 언급됨. 현재 증상 여부는 별도 판단.",
            "negated": "해당 증상 자체가 부정됨.",
            "not_symptom": "단어는 있지만 환자의 증상 언급이 아님.",
            "uncertain": "증상의 존재를 확정하지 않은 언급.",
        },
        "input_file": "queries.jsonl",
        "criteria_file": "criteria.jsonl",
        "baselines": baselines,
    })

    # 원본을 수정하지 않고 새 실험 폴더에만 작성한다.
    args.output.mkdir(parents=True, exist_ok=False)
    for relative, content in payloads.items():
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as file:
            file.write(content)

    for baseline in baselines:
        expected = baseline["sha256"]
        original = Path(baseline["original_path"])
        snapshot = args.output / baseline["snapshot_path"]
        if (
            hashlib.sha256(original.read_bytes()).hexdigest() != expected
            or hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("기준 파일 보존 확인에 실패했습니다.")

    print("기준 코드·결과 보존:", len(baselines), "개")
    print("개발 입력:", len(queries), "건")
    print("판정 초안:", len(criteria), "건 / 사람 검토 전")
    print("실험 폴더:", args.output)
    print("표현 정규화 실험 준비 완료")


if __name__ == "__main__":
    main()

