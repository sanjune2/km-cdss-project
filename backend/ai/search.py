from fractions import Fraction


MAX_KEYWORD_CANDIDATES = 30
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