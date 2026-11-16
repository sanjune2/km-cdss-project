import argparse
import json
import math
from pathlib import Path

import numpy as np


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


def check_chunk_links(
    chunks: list[dict],
    embeddings: list[dict],
    disease_ids: set,
    prescription_ids: set,
) -> None:
    if not chunks or not embeddings:
        raise ValueError("원문 조각 또는 임베딩 결과가 비어 있습니다.")

    chunk_ids = check_unique_ids(chunks, "chunk_id", "원문 조각", str)
    vector_ids = check_unique_ids(embeddings, "chunk_id", "임베딩 결과", str)

    if chunk_ids != vector_ids:
        raise ValueError("원문 조각과 임베딩 결과의 chunk_id 목록이 다릅니다.")

    vectors_by_id = {row["chunk_id"]: row for row in embeddings}
    allowed_entities = {
        "disease": disease_ids,
        "prescription": prescription_ids,
    }
    used_rows = set()

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        entity_type = chunk.get("entity_type")
        entity_id = chunk.get("entity_id")

        if type(entity_type) is not str or entity_type not in allowed_entities:
            raise ValueError(f"{chunk_id}: 병증·처방 구분이 올바르지 않습니다.")

        if type(entity_id) is not int or entity_id not in allowed_entities[entity_type]:
            raise ValueError(f"{chunk_id}: 연결된 기업 항목이 없습니다.")

        document_id = chunk.get("document_id")
        if type(document_id) is not str or not document_id.strip():
            raise ValueError(f"{chunk_id}: document_id가 올바르지 않습니다.")

        row_number = chunk.get("embedding_row")
        if type(row_number) is not int or row_number < 0:
            raise ValueError(f"{chunk_id}: 벡터 행번호가 올바르지 않습니다.")

        if row_number in used_rows:
            raise ValueError(f"{chunk_id}: 벡터 행번호 {row_number} 중복")

        used_rows.add(row_number)
        vector = vectors_by_id[chunk_id]

        for key in ("document_id", "entity_type", "entity_id", "embedding_row"):
            if (
                key not in vector
                or type(vector[key]) is not type(chunk[key])
                or vector[key] != chunk[key]
            ):
                raise ValueError(f"{chunk_id}: 조각·벡터의 {key} 불일치")

    if used_rows != set(range(len(embeddings))):
        raise ValueError("벡터 행번호가 0부터 누락 없이 연결되지 않았습니다.")

    print(f"[통과] 원문 조각·벡터·기업 항목 연결 검사: {len(chunks)}건")


def check_vector_contents(
    chunks: list[dict],
    embeddings: list[dict],
) -> None:
    expected_model = "intfloat/multilingual-e5-small"
    expected_revision = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

    for label, rows in (("원문 조각", chunks), ("임베딩 결과", embeddings)):
        for row in rows:
            chunk_id = row.get("chunk_id")

            if row.get("model_id") != expected_model:
                raise ValueError(f"{label} {chunk_id}: 임베딩 모델 불일치")

            if row.get("model_revision") != expected_revision:
                raise ValueError(f"{label} {chunk_id}: 모델 버전 불일치")

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]

        if (
            chunk.get("embedding_status") != "SUCCESS"
            or chunk.get("embedding_failure") is not None
        ):
            raise ValueError(f"{chunk_id}: 임베딩 성공 상태가 아닙니다.")

        if chunk.get("model_input_prefix") != "passage: ":
            raise ValueError(f"{chunk_id}: 자료 임베딩 접두어 불일치")

    for row in embeddings:
        chunk_id = row["chunk_id"]
        vector = row.get("embedding")

        if type(row.get("dimensions")) is not int or row["dimensions"] != 384:
            raise ValueError(f"{chunk_id}: 차원 정보가 384가 아닙니다.")

        if not isinstance(vector, list) or len(vector) != 384:
            raise ValueError(f"{chunk_id}: 실제 벡터 길이가 384가 아닙니다.")

        for value in vector:
            if type(value) not in (int, float):
                raise ValueError(f"{chunk_id}: 벡터에 숫자가 아닌 값이 있습니다.")

            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False

            if not finite:
                raise ValueError(f"{chunk_id}: 벡터에 유효하지 않은 수치가 있습니다.")

        if row.get("dtype") != "float32" or row.get("normalized") is not True:
            raise ValueError(f"{chunk_id}: 벡터 자료형·정규화 기록 불일치")

        norm = math.hypot(*vector)
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-5):
            raise ValueError(f"{chunk_id}: L2 정규화 값이 1에서 벗어났습니다.")

    print("[통과] 임베딩 모델·버전·성공 상태 검사")
    print(f"[통과] 384차원·유한수·L2 정규화 검사: {len(embeddings)}건")


def check_npy_matrix(path: Path, embeddings: list[dict]) -> None:
    matrix = np.load(path, allow_pickle=False)

    if not isinstance(matrix, np.ndarray):
        raise ValueError("NPY 파일이 숫자 배열 형식이 아닙니다.")

    expected_shape = (len(embeddings), 384)
    if matrix.shape != expected_shape:
        raise ValueError(
            f"NPY 배열 크기 불일치: {matrix.shape}, 예상: {expected_shape}"
        )

    if matrix.dtype != np.dtype("float32"):
        raise ValueError(f"NPY 자료형 불일치: {matrix.dtype}")

    if not np.isfinite(matrix).all():
        raise ValueError("NPY 벡터에 유효하지 않은 수치가 있습니다.")

    for row in embeddings:
        row_number = row["embedding_row"]
        expected_vector = np.asarray(row["embedding"], dtype=np.float64)
        actual_vector = matrix[row_number].astype(np.float64)

        if not np.array_equal(actual_vector, expected_vector):
            raise ValueError(
                f"{row['chunk_id']}: NPY와 JSONL 벡터 값 불일치"
            )

    print(
        f"[통과] NPY·JSONL 벡터 값 일치: "
        f"{matrix.shape[0]}건 × {matrix.shape[1]}차원, {matrix.dtype}"
    )


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

    chunks = loaded_files["stage2/청킹결과.jsonl"]
    embeddings = loaded_files["stage2/임베딩결과.jsonl"]

    check_chunk_links(
        chunks,
        embeddings,
        disease_ids,
        prescription_ids,
    )

    check_vector_contents(chunks, embeddings)

    check_npy_matrix(
        args.data_root / "stage2/벡터행렬.npy",
        embeddings,
    )

    print("자료 연결·벡터 검사 완료")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f"검사 실패: {error}")