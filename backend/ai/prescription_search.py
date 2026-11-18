import hashlib

import numpy as np

from .embedding import E5Embedder


def get_linked_prescriptions(
    selected_disease_id: int,
    diseases: list[dict],
    prescriptions: list[dict],
    relations: list[dict],
) -> list[dict]:
    if type(selected_disease_id) is not int or selected_disease_id <= 0:
        raise ValueError("선택 병증 식별번호가 올바르지 않습니다.")

    disease_ids = {row["DIS_UNIQN"] for row in diseases}
    if selected_disease_id not in disease_ids:
        raise ValueError("선택한 병증이 등록 자료에 없습니다.")

    prescriptions_by_id = {
        row["PRESP_UNIQN"]: row for row in prescriptions
    }
    linked_ids = {
        row["PRESP_UNIQN"]
        for row in relations
        if row["DIS_UNIQN"] == selected_disease_id
    }

    missing_ids = linked_ids - prescriptions_by_id.keys()
    if missing_ids:
        raise ValueError(
            f"연결된 처방 원문이 없습니다: {sorted(missing_ids)}"
        )

    return sorted(
        [prescriptions_by_id[value] for value in linked_ids],
        key=lambda row: (row["PRESP_NM"], row["PRESP_UNIQN"]),
    )


def score_prescriptions(
    query_vector: np.ndarray,
    linked_prescriptions: list[dict],
    chunks: list[dict],
    matrix: np.ndarray,
) -> dict:
    query = np.asarray(query_vector, dtype=np.float64)
    if query.shape != (384,) or not np.isfinite(query).all():
        raise ValueError("입력 벡터는 유효한 숫자 384개여야 합니다.")

    query_norm = np.linalg.norm(query)
    if not np.isfinite(query_norm) or query_norm == 0:
        raise ValueError("입력 벡터의 길이가 올바르지 않습니다.")

    if matrix.ndim != 2 or matrix.shape[1] != 384:
        raise ValueError("처방 벡터 배열 크기가 올바르지 않습니다.")

    linked_ids = {row["PRESP_UNIQN"] for row in linked_prescriptions}
    if len(linked_ids) != len(linked_prescriptions):
        raise ValueError("연결 처방 목록에 중복 식별번호가 있습니다.")

    chunks_by_id = {}
    for chunk in chunks:
        if (
            chunk["entity_type"] == "prescription"
            and chunk["entity_id"] in linked_ids
        ):
            chunks_by_id.setdefault(
                chunk["entity_id"], []
            ).append(chunk)

    scored = []
    unscored = []

    for prescription in linked_prescriptions:
        prescription_id = prescription["PRESP_UNIQN"]
        available = prescription["semantic_available"]
        text = prescription["semantic_text"].strip()

        if type(available) is not bool or available != bool(text):
            raise ValueError(
                f"{prescription_id}: 처방 설명 상태가 일치하지 않습니다."
            )

        own_chunks = chunks_by_id.get(prescription_id, [])
        item = {
            "id": prescription_id,
            "name": prescription["PRESP_NM"],
            "score": None,
            "rank": None,
            "bestChunkId": None,
        }

        if not available:
            if own_chunks:
                raise ValueError(
                    f"{prescription_id}: 설명 없는 처방에 조각이 연결됐습니다."
                )
            unscored.append({
                **item,
                "evaluationStatus": "INSUFFICIENT_DATA",
            })
            continue

        if not own_chunks:
            raise ValueError(
                f"{prescription_id}: 처방 설명의 임베딩 조각이 없습니다."
            )

        row_numbers = [
            chunk["embedding_row"] for chunk in own_chunks
        ]
        if any(
            type(value) is not int or not 0 <= value < len(matrix)
            for value in row_numbers
        ):
            raise ValueError(
                f"{prescription_id}: 벡터 행번호가 올바르지 않습니다."
            )

        vectors = matrix[row_numbers].astype(np.float64)
        if not np.isfinite(vectors).all():
            raise ValueError(
                f"{prescription_id}: 벡터에 유효하지 않은 수치가 있습니다."
            )

        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(norms).all() or np.any(norms == 0):
            raise ValueError(
                f"{prescription_id}: 벡터의 길이가 올바르지 않습니다."
            )

        similarities = (
            (vectors / norms[:, None]) @ (query / query_norm)
        )
        similarities = np.clip(similarities, -1.0, 1.0)
        best_index = int(np.argmax(similarities))

        scored.append({
            **item,
            "score": float(similarities[best_index]),
            "bestChunkId": own_chunks[best_index]["chunk_id"],
            "evaluationStatus": "SCORED",
        })

    scored.sort(
        key=lambda row: (-row["score"], row["name"], row["id"])
    )
    for rank, item in enumerate(scored, start=1):
        item["rank"] = rank

    unscored.sort(key=lambda row: (row["name"], row["id"]))

    return {
        "candidates": scored,
        "unscoredCandidates": unscored,
        "summary": {
            "connectedCount": len(linked_prescriptions),
            "scoredCount": len(scored),
            "insufficientCount": len(unscored),
            "policyUnconfiguredCount": 0,
        },
    }


def search_prescriptions(
    symptoms: str,
    selected_disease_id: int,
    embedder: E5Embedder,
    diseases: list[dict],
    prescriptions: list[dict],
    relations: list[dict],
    chunks: list[dict],
    matrix: np.ndarray,
    compositions: list[dict],
    herbs: list[dict],
) -> dict:
    text = symptoms.strip()
    if not text:
        raise ValueError("증상을 입력해주세요.")

    linked = get_linked_prescriptions(
        selected_disease_id,
        diseases,
        prescriptions,
        relations,
    )

    if not linked:
        return {
            "symptoms": text,
            "selectedDiseaseId": selected_disease_id,
            "candidates": [],
            "unscoredCandidates": [],
            "summary": {
                "connectedCount": 0,
                "scoredCount": 0,
                "insufficientCount": 0,
                "policyUnconfiguredCount": 0,
            },
            "message": "기업 자료에 연결된 처방이 없습니다",
        }

    query_vector = embedder.encode_query(text)
    result = score_prescriptions(
        query_vector,
        linked,
        chunks,
        matrix,
    )

    for group in ("candidates", "unscoredCandidates"):
        for candidate in result[group]:
            candidate["evidenceSources"] = build_prescription_evidence(
                candidate,
                prescriptions,
                chunks,
            )

            candidate["ingredients"] = get_prescription_ingredients(
                candidate["id"],
                compositions,
                herbs,
            )

            candidate.update(
                build_prescription_caution(
                    candidate["id"],
                    prescriptions,
                    candidate["ingredients"],
                    herbs,
                )
            )

    message = None
    if not result["candidates"]:
        message = "연결 처방은 있으나 설명 평가 자료가 없습니다"
    elif result["unscoredCandidates"]:
        message = (
            "일부 연결 처방은 자체 설명이 없어 "
            "연관성을 평가하지 못했습니다."
        )

    return {
        "symptoms": text,
        "selectedDiseaseId": selected_disease_id,
        **result,
        "message": message,
    }


def build_prescription_evidence(
    candidate: dict,
    prescriptions: list[dict],
    chunks: list[dict],
) -> list[dict]:
    if candidate["evaluationStatus"] != "SCORED":
        return []

    prescription = next(
        (
            row for row in prescriptions
            if row["PRESP_UNIQN"] == candidate["id"]
        ),
        None,
    )
    chunk = next(
        (
            row for row in chunks
            if row["chunk_id"] == candidate["bestChunkId"]
        ),
        None,
    )

    if prescription is None or chunk is None:
        raise ValueError("처방 근거의 원문 또는 조각이 없습니다.")

    if (
        chunk["entity_type"] != "prescription"
        or chunk["entity_id"] != candidate["id"]
        or chunk["source"] != prescription["source"]
    ):
        raise ValueError("처방과 근거 조각의 연결이 일치하지 않습니다.")

    original = prescription["PRESP_CONT"]
    original_hash = hashlib.sha256(
        original.encode("utf-8")
    ).hexdigest()

    if original_hash != chunk["original_text_sha256"]:
        raise ValueError("처방 원문 버전이 근거 조각과 다릅니다.")

    start = chunk["source_start"]
    end = chunk["source_end"]

    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(original)
        or original[start:end] != chunk["text"]
    ):
        raise ValueError("처방 근거의 발췌 위치 또는 내용이 다릅니다.")

    source = prescription["source"]
    version = source["file_sha256"]

    return [{
        "sourceId": f"PRESP-{candidate['id']}-PRESP_CONT-{version}",
        "sourceTitle": f"기업 처방 설명 · {prescription['PRESP_NM']}",
        "dataVersion": f"sha256:{version}",
        "fileName": source["file"],
        "sheet": source["sheet"],
        "column": "PRESP_CONT",
        "sourceLocation": (
            f"{source['sheet']}!"
            f"{source['cells']['PRESP_CONT']}"
        ),
        "itemId": candidate["id"],
        "row": source["row"],
        "excerpt": chunk["text"],
        "originalText": original,
        "chunkId": chunk["chunk_id"],
        "sourceStart": start,
        "sourceEnd": end,
    }]


def get_prescription_ingredients(
    prescription_id: int,
    compositions: list[dict],
    herbs: list[dict],
) -> list[dict]:
    if type(prescription_id) is not int or prescription_id <= 0:
        raise ValueError("처방 식별번호가 올바르지 않습니다.")

    herbs_by_id = {row["MED_UNIQN"]: row for row in herbs}
    if len(herbs_by_id) != len(herbs):
        raise ValueError("약재 원문에 중복 식별번호가 있습니다.")

    def original_or_none(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("약재 구성 원본값은 문자열이어야 합니다.")
        return value if value.strip() else None

    ingredients = []
    seen = set()

    for row in compositions:
        if row["PRESP_UNIQN"] != prescription_id:
            continue

        composition_id = row["RSHIP_UNIQN"]
        if composition_id in seen:
            raise ValueError("처방 약재 구성 행이 중복됐습니다.")
        seen.add(composition_id)

        herb = herbs_by_id.get(row["MED_UNIQN"])
        if herb is None:
            raise ValueError(
                f"약재 원문이 없습니다: {row['MED_UNIQN']}"
            )
        if not herb["MED_NM"].strip():
            raise ValueError("등록된 약재명이 비어 있습니다.")

        ingredients.append({
            "compositionId": composition_id,
            "id": row["MED_UNIQN"],
            "name": herb["MED_NM"],
            "amount": original_or_none(row["UNT_COEFF"]),
            "unit": original_or_none(row["UNT"]),
            "preparation": original_or_none(row["MED_SPEC_REP"]),
            "originalDoseInfo": original_or_none(row["CC_INFO"]),
        })

    return ingredients


def build_prescription_caution(
    prescription_id: int,
    prescriptions: list[dict],
    ingredients: list[dict],
    herbs: list[dict],
) -> dict:
    prescription = next(
        (
            row for row in prescriptions
            if row["PRESP_UNIQN"] == prescription_id
        ),
        None,
    )
    if prescription is None:
        raise ValueError("주의정보를 조회할 처방 원문이 없습니다.")

    herbs_by_id = {row["MED_UNIQN"]: row for row in herbs}
    if len(herbs_by_id) != len(herbs):
        raise ValueError("약재 원문에 중복 식별번호가 있습니다.")

    sources = []

    def collect(
        row: dict,
        kind: str,
        item_id: int,
        name: str,
    ) -> None:
        text = row["TABO_CONT"]
        if not isinstance(text, str):
            raise ValueError("등록 주의 원문의 형식이 올바르지 않습니다.")

        if text.strip():
            sources.append({
                "entityType": kind,
                "itemId": item_id,
                "name": name,
                "column": "TABO_CONT",
                "text": text,
                "source": dict(row["source"]),
            })

    collect(
        prescription,
        "prescription",
        prescription_id,
        prescription["PRESP_NM"],
    )

    seen = set()
    for ingredient in ingredients:
        herb_id = ingredient["id"]
        herb = herbs_by_id.get(herb_id)

        if herb is None:
            raise ValueError(
                f"주의정보의 약재 원문이 없습니다: {herb_id}"
            )

        if herb_id in seen:
            continue
        seen.add(herb_id)

        collect(herb, "herb", herb_id, herb["MED_NM"])

    reasons = ["주의정보 대조 규칙을 아직 검토하지 않았습니다."]

    if not sources:
        reasons.append(
            "처방과 구성 약재에 등록된 주의 원문이 없습니다."
        )

    reasons.append("환자별 주의정보 대조는 수행하지 않았습니다.")

    return {
        "caution": {
            "status": "RULES_NOT_REVIEWED",
            "registeredTexts": [row["text"] for row in sources],
            "message": " ".join(reasons),
        },
        "cautionSources": sources,
    }