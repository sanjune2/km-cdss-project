import argparse
import json
from pathlib import Path


DATA_FILES = (
    "stage1/검색용/병증원문.jsonl",
    "stage1/검색용/키워드검색항목.jsonl",
    "stage1/검색용/처방원문.jsonl",
    "stage1/조회용/병증처방관계.jsonl",
    "stage2/청킹결과.jsonl",
    "stage2/임베딩결과.jsonl",
)


def read_jsonl(path: Path) -> list[dict]:
    rows = []

    with path.open(encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path.name} {line_number}행: JSON 형식 오류"
                ) from error

            if not isinstance(row, dict):
                raise ValueError(
                    f"{path.name} {line_number}행: 객체 형식이 아닙니다."
                )

            rows.append(row)

    return rows


def check_unique_ids(
    rows: list[dict],
    key: str,
    label: str,
    expected_type: type,
) -> set:
    seen = set()

    for position, row in enumerate(rows, start=1):
        value = row.get(key)

        if type(value) is not expected_type:
            raise ValueError(
                f"{label} {position}번째 자료: {key} 자료형 오류"
            )

        if expected_type is int and value <= 0:
            raise ValueError(
                f"{label} {position}번째 자료: {key}는 1 이상이어야 합니다."
            )

        if expected_type is str and not value.strip():
            raise ValueError(
                f"{label} {position}번째 자료: {key}가 비어 있습니다."
            )

        if value in seen:
            raise ValueError(f"{label}: {key}={value!r} 중복")

        seen.add(value)

    print(f"[통과] {label} 식별번호 형식·중복 검사")
    return seen


def check_references(
    rows: list[dict],
    key: str,
    allowed_ids: set,
    label: str,
) -> None:
    for position, row in enumerate(rows, start=1):
        value = row.get(key)

        if type(value) is not int or value not in allowed_ids:
            raise ValueError(
                f"{label} {position}번째 자료: "
                f"연결 대상 {key}={value!r}를 찾을 수 없습니다."
            )

    print(f"[통과] {label} 연결 검사")


def main() -> None:
    parser = argparse.ArgumentParser(description="검색 자료 적재 전 검사")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true", required=True)
    args = parser.parse_args()

    loaded_files = {}

    for relative_path in DATA_FILES:
        path = args.data_root / relative_path
        rows = read_jsonl(path)
        loaded_files[relative_path] = rows
        print(f"{relative_path}: {len(rows)}건")

    diseases = loaded_files["stage1/검색용/병증원문.jsonl"]
    prescriptions = loaded_files["stage1/검색용/처방원문.jsonl"]
    keywords = loaded_files["stage1/검색용/키워드검색항목.jsonl"]
    relations = loaded_files["stage1/조회용/병증처방관계.jsonl"]

    disease_ids = check_unique_ids(diseases, "DIS_UNIQN", "병증", int)
    prescription_ids = check_unique_ids(
        prescriptions, "PRESP_UNIQN", "처방", int
    )
    check_unique_ids(keywords, "term_id", "키워드 항목", str)
    check_unique_ids(relations, "RSHIP_UNIQN", "병증·처방 관계", int)

    check_references(keywords, "DIS_UNIQN", disease_ids, "키워드→병증")
    check_references(relations, "DIS_UNIQN", disease_ids, "관계→병증")
    check_references(
        relations, "PRESP_UNIQN", prescription_ids, "관계→처방"
    )

    linked_disease_ids = {row["DIS_UNIQN"] for row in relations}
    unlinked_count = len(disease_ids - linked_disease_ids)
    print(f"[정보] 연결 처방이 없는 병증: {unlinked_count}건")

    print("식별번호 및 연결 검사 완료")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f"검사 실패: {error}")