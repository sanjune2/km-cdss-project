MAX_KEYWORD_CANDIDATES = 30


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