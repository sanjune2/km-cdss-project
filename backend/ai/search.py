from fractions import Fraction

import numpy as np

from .embedding import E5Embedder


MAX_KEYWORD_CANDIDATES = 30
MAX_SEMANTIC_CANDIDATES = 30
RRF_K = 60


def search_keywords(
    symptoms: str,
    diseases: list[dict],
    keywords: list[dict],
) -> list[int]:
    query = symptoms.strip()
    if not query:
        return []

    disease_names = {
        row["DIS_UNIQN"]: row["ATT_DIS_NM"]
        for row in diseases
    }
    matched_ids = set()

    for row in keywords:
        if query not in row["term"]:
            continue

        disease_id = row["DIS_UNIQN"]
        if disease_id not in disease_names:
            raise ValueError(
                f"키워드에 연결된 병증 식별번호 {disease_id}가 없습니다."
            )

        matched_ids.add(disease_id)

    ordered_ids = sorted(
        matched_ids,
        key=lambda disease_id: (disease_names[disease_id], disease_id),
    )
    return ordered_ids[:MAX_KEYWORD_CANDIDATES]


def fuse_rrf(
    keyword_ids: list[int],
    semantic_ids: list[int],
    diseases: list[dict],
) -> list[dict]:
    disease_names = {
        row["DIS_UNIQN"]: row["ATT_DIS_NM"]
        for row in diseases
    }
    scores = {}

    for label, ranked_ids in (
        ("키워드", keyword_ids),
        ("의미", semantic_ids),
    ):
        seen = set()

        for position, disease_id in enumerate(ranked_ids, start=1):
            if type(disease_id) is not int or disease_id not in disease_names:
                raise ValueError(
                    f"{label} 검색의 병증 식별번호 {disease_id!r}가 올바르지 않습니다."
                )

            if disease_id in seen:
                raise ValueError(f"{label} 검색에 병증 {disease_id}가 중복됐습니다.")

            seen.add(disease_id)
            scores[disease_id] = (
                scores.get(disease_id, Fraction(0, 1))
                + Fraction(1, RRF_K + position)
            )

    ordered_ids = sorted(
        scores,
        key=lambda disease_id: (
            -scores[disease_id],
            disease_names[disease_id],
            disease_id,
        ),
    )

    return [
        {
            "id": disease_id,
            "name": disease_names[disease_id],
            "score": float(scores[disease_id]),
            "rank": rank,
        }
        for rank, disease_id in enumerate(ordered_ids, start=1)
    ]


def search_semantic(
    query_vector: np.ndarray,
    diseases: list[dict],
    chunks: list[dict],
    matrix: np.ndarray,
) -> list[dict]:
    query = np.asarray(query_vector, dtype=np.float64)
    if query.shape != (384,) or not np.isfinite(query).all():
        raise ValueError("입력 벡터는 유효한 숫자 384개여야 합니다.")

    query_norm = np.linalg.norm(query)
    if not np.isfinite(query_norm) or query_norm == 0:
        raise ValueError("입력 벡터의 길이가 올바르지 않습니다.")

    if matrix.ndim != 2 or matrix.shape[1] != 384:
        raise ValueError("검색 자료의 벡터 배열 크기가 올바르지 않습니다.")

    disease_names = {
        row["DIS_UNIQN"]: row["ATT_DIS_NM"]
        for row in diseases
    }
    disease_chunks = [
        row for row in chunks
        if row["entity_type"] == "disease"
    ]
    if not disease_chunks:
        raise ValueError("병증 검색에 사용할 원문 조각이 없습니다.")

    row_numbers = []
    for chunk in disease_chunks:
        disease_id = chunk["entity_id"]
        row_number = chunk["embedding_row"]

        if type(disease_id) is not int or disease_id not in disease_names:
            raise ValueError(f"{chunk['chunk_id']}: 연결된 병증이 없습니다.")

        if type(row_number) is not int or not 0 <= row_number < len(matrix):
            raise ValueError(f"{chunk['chunk_id']}: 벡터 행번호 오류")

        row_numbers.append(row_number)

    vectors = matrix[row_numbers].astype(np.float64)
    if not np.isfinite(vectors).all():
        raise ValueError("병증 벡터에 유효하지 않은 수치가 있습니다.")

    norms = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(norms).all() or np.any(norms == 0):
        raise ValueError("병증 벡터의 길이가 올바르지 않습니다.")

    similarities = (vectors / norms[:, None]) @ (query / query_norm)
    similarities = np.clip(similarities, -1.0, 1.0)
    best_by_disease = {}

    for chunk, similarity in zip(disease_chunks, similarities):
        disease_id = chunk["entity_id"]
        score = float(similarity)
        previous = best_by_disease.get(disease_id)

        if previous is None or score > previous["semanticScore"]:
            best_by_disease[disease_id] = {
                "id": disease_id,
                "name": disease_names[disease_id],
                "semanticScore": score,
                "bestChunkId": chunk["chunk_id"],
            }

    ranked = sorted(
        best_by_disease.values(),
        key=lambda row: (-row["semanticScore"], row["name"], row["id"]),
    )[:MAX_SEMANTIC_CANDIDATES]

    return [
        {**row, "rank": rank}
        for rank, row in enumerate(ranked, start=1)
    ]


def search_hybrid(
    symptoms: str,
    embedder: E5Embedder,
    diseases: list[dict],
    keywords: list[dict],
    chunks: list[dict],
    matrix: np.ndarray,
) -> dict:
    text = symptoms.strip()
    if not text:
        raise ValueError("증상을 입력해주세요.")

    keyword_ids = search_keywords(text, diseases, keywords)
    query_vector = embedder.encode_query(text)
    semantic_candidates = search_semantic(
        query_vector,
        diseases,
        chunks,
        matrix,
    )
    semantic_ids = [row["id"] for row in semantic_candidates]
    candidates = fuse_rrf(keyword_ids, semantic_ids, diseases)

    return {
        "symptoms": text,
        "keywordIds": keyword_ids,
        "semanticCandidates": semantic_candidates,
        "candidates": candidates,
    }