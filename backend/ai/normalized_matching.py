MATCH_POLICY_VERSION = "normalized_unit_occurrences_v1"


def unit_signature(units: list[dict]) -> tuple:
    if not units:
        return ()
    first_segment = units[0]["segment"]
    return tuple(
        (unit["form"], unit["tag"], unit["segment"] - first_segment)
        for unit in units
    )


def build_keyword_index(
    registered_terms: list[dict],
    keyword_links: list[dict],
) -> dict:
    signatures = {}
    for row in registered_terms:
        term = row["term"]
        if term in signatures:
            raise ValueError("정규화한 등록 표현이 중복됐습니다.")
        signatures[term] = unit_signature(row["search_units"])

    by_length = {}
    skipped = []
    seen_ids = set()

    for link in keyword_links:
        term_id = link["term_id"]
        if term_id in seen_ids:
            raise ValueError("등록 번호가 중복됐습니다.")
        seen_ids.add(term_id)

        term = link["term"]
        if term not in signatures:
            raise ValueError(f"등록 표현의 정규화 자료가 없습니다: {term_id}")

        signature = signatures[term]
        if not signature:
            skipped.append({
                "term_id": term_id,
                "term": term,
                "reason": "비교 가능한 정규화 단위 없음",
            })
            continue

        by_length.setdefault(len(signature), {}).setdefault(
            signature, []
        ).append(dict(link))

    return {
        "by_length": by_length,
        "skipped_links": skipped,
        "indexed_link_count": len(seen_ids) - len(skipped),
    }


def find_normalized_matches(
    text: str,
    analysis: dict,
    index: dict,
) -> list[dict]:
    units = analysis["search_units"]
    tokens = analysis["tokens"]
    matches = []

    for width, signatures in index["by_length"].items():
        for offset in range(len(units) - width + 1):
            window = units[offset:offset + width]
            links = signatures.get(unit_signature(window), [])
            if not links:
                continue

            token_indices = [unit["token_index"] for unit in window]
            if any(
                type(value) is not int or not 0 <= value < len(tokens)
                for value in token_indices
            ):
                raise ValueError("정규화 단위의 토큰 위치가 올바르지 않습니다.")

            selected = [tokens[value] for value in token_indices]
            start = min(token["start"] for token in selected)
            end = max(token["start"] + token["length"] for token in selected)
            if not 0 <= start < end <= len(text):
                raise ValueError("표현 일치의 원문 위치가 올바르지 않습니다.")

            for link in links:
                matches.append({
                    "term_id": link["term_id"],
                    "registered_term": link["term"],
                    "term_type": link["term_type"],
                    "disease_id": link["disease_id"],
                    "start": start,
                    "end": end,
                    "matched_text": text[start:end],
                    "token_start_index": min(token_indices),
                    "token_end_index": max(token_indices) + 1,
                    "assertion_status": "UNASSESSED",
                    "symptom_context_status": "UNASSESSED",
                })

    return sorted(
        matches,
        key=lambda row: (
            row["start"], row["end"], row["term_id"], row["disease_id"]
        ),
    )

