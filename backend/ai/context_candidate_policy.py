"""저장된 문맥 판정의 키워드 후보 연결 실험. 운영 검색에는 연결하지 않는다."""
from collections import Counter

POLICY_VERSION = "affirmed_keyword_support_review_uncertain_v1"
MAX_KEYWORD_CANDIDATES = 30
CONTEXTS = {"PATIENT_SYMPTOM", "BODY_SITE_ONLY", "NON_SYMPTOM", "UNASSESSED"}
ASSERTIONS = {"AFFIRMED", "NEGATED", "UNCERTAIN", "UNASSESSED"}


def decision_for(context, assertion):
    if context not in CONTEXTS or assertion not in ASSERTIONS:
        raise ValueError("알 수 없는 문맥 또는 존재 판정입니다.")
    if context != "PATIENT_SYMPTOM" and assertion != "UNASSESSED":
        raise ValueError("증상 문맥이 아닌 범위에 존재 판정이 지정됐습니다.")
    if context == "BODY_SITE_ONLY":
        return "IGNORE_BODY_SITE"
    if context == "NON_SYMPTOM":
        return "IGNORE_NON_SYMPTOM"
    if context == "UNASSESSED":
        return "REVIEW_CONTEXT"
    if assertion == "AFFIRMED":
        return "ACCEPT_KEYWORD_SUPPORT"
    if assertion == "NEGATED":
        return "IGNORE_NEGATED_SUPPORT"
    return "REVIEW_ASSERTION"


def partition_context_case(case, disease_names):
    if case.get("status") != "STRUCTURE_VALID":
        raise ValueError("분류를 끝내지 못한 사례는 후보에 연결할 수 없습니다.")
    text = case["input_text"]
    inputs = case["model_input"]
    if inputs["input_text"] != text:
        raise ValueError("모델 입력과 원문이 다릅니다.")
    source_mentions = {m["mention_id"]: m for m in inputs["mentions"]}
    decisions = {m["mention_id"]: m for m in case["mentions"]}
    if (len(source_mentions) != len(inputs["mentions"])
            or len(decisions) != len(case["mentions"])
            or set(source_mentions) != set(decisions)):
        raise ValueError("원문 범위와 분류 결과의 식별번호가 다릅니다.")
    span_decisions = []
    for mention_id, m in decisions.items():
        source = source_mentions[mention_id]
        start, end = source["start"], source["end"]
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)
                or text[start:end] != source["matched_text"]
                or (m["source_start"], m["source_end"], m["source_text"])
                != (start, end, source["matched_text"])):
            raise ValueError("분류 결과의 원문 위치가 다릅니다.")
        state = decision_for(m["context"], m["assertion"])
        span_decisions.append({
            "mention_id": mention_id, "start": start, "end": end,
            "source_text": text[start:end], "registered_terms": source["registered_terms"],
            "context": m["context"], "assertion": m["assertion"],
            "candidate_policy_status": state,
        })
    states = {m["mention_id"]: m["candidate_policy_status"] for m in span_decisions}
    raw_ids, accepted_ids, review_ids = set(), set(), set()
    evidence, links = {}, []
    seen_links = set()
    linked_mentions = set()
    for row in case["keyword_matches"]:
        mention_id = row["context_mention_id"]
        if mention_id not in decisions:
            raise ValueError("키워드 연결의 문맥 범위가 없습니다.")
        source, m = source_mentions[mention_id], decisions[mention_id]
        if ((row["start"], row["end"], row["matched_text"])
                != (source["start"], source["end"], source["matched_text"])
                or row["registered_term"] not in source["registered_terms"]
                or row["assertion_status"] != m["assertion"]
                or row["symptom_context_status"] != m["context"]):
            raise ValueError("키워드 연결과 문맥 판정이 다릅니다.")
        disease_id = row["disease_id"]
        if type(disease_id) is not int or disease_id not in disease_names:
            raise ValueError("키워드 연결의 병증 식별번호가 올바르지 않습니다.")
        if row["disease_name"] != disease_names[disease_id]:
            raise ValueError("병증 원문과 연결된 병증명이 다릅니다.")
        identity = (row["term_id"], disease_id, row["start"], row["end"])
        if identity in seen_links:
            raise ValueError("같은 위치의 동일 키워드 연결이 중복됐습니다.")
        seen_links.add(identity)
        linked_mentions.add(mention_id)
        state = states[mention_id]
        raw_ids.add(disease_id)
        if state == "ACCEPT_KEYWORD_SUPPORT":
            accepted_ids.add(disease_id)
        elif state.startswith("REVIEW_"):
            review_ids.add(disease_id)
        evidence.setdefault(disease_id, Counter())[state] += 1
        links.append({**row, "candidate_policy_status": state})
    if linked_mentions != set(decisions):
        raise ValueError("키워드 연결에 대응하지 않는 분류 범위가 있습니다.")

    def ordered(ids):
        return sorted(ids, key=lambda item: (disease_names[item], item))

    all_raw, all_accepted = ordered(raw_ids), ordered(accepted_ids)
    return {
        "case_id": case["case_id"], "input_text": text,
        "normalizedKeywordIds": all_raw[:MAX_KEYWORD_CANDIDATES],
        "contextKeywordIds": all_accepted[:MAX_KEYWORD_CANDIDATES],
        "allNormalizedKeywordIds": all_raw,
        "allContextKeywordIds": all_accepted,
        "reviewKeywordIds": ordered(review_ids),
        "removedNormalizedKeywordIds": ordered(raw_ids - accepted_ids),
        "mentions": span_decisions, "keyword_matches": links,
        "disease_evidence": [
            {"id": item, "name": disease_names[item],
             "link_counts": dict(evidence[item]),
             "has_affirmed_and_negated_support": (
                 evidence[item]["ACCEPT_KEYWORD_SUPPORT"] > 0
                 and evidence[item]["IGNORE_NEGATED_SUPPORT"] > 0
             )}
            for item in all_raw
        ],
        "summary": {
            "spans": len(span_decisions), "links": len(links),
            "span_policy_counts": dict(Counter(m["candidate_policy_status"] for m in span_decisions)),
            "link_policy_counts": dict(Counter(m["candidate_policy_status"] for m in links)),
            "normalized_diseases_before_limit": len(raw_ids),
            "context_diseases_before_limit": len(accepted_ids),
            "candidate_limit": MAX_KEYWORD_CANDIDATES,
            "normalized_truncated_count": max(0, len(raw_ids) - MAX_KEYWORD_CANDIDATES),
            "context_truncated_count": max(0, len(accepted_ids) - MAX_KEYWORD_CANDIDATES),
        },
        "used_in_search": False,
    }
