"""Compare explanation candidates with the versioned corporate search inputs."""


def check_record(check_type, target, required, status, reason=None):
    return {"checkType": check_type, "target": target, "required": required,
            "status": status, "reason": reason}


def verify_candidate(search, candidate, runtime, catalog):
    context = search["INPUT_CONTEXT"]
    is_disease = context["kind"] == "DISEASE"
    kind = "disease" if is_disease else "prescription"
    item_id = candidate["id"]
    disease_id = item_id if is_disease else context["selectedDiseaseId"]
    tables, links, compositions = catalog
    source = tables[kind].get(item_id)
    target = {"kind": kind, "id": item_id}
    checks = []

    def add(check_type, ok, detail, applies=True, **data):
        checks.append(check_record(
            check_type, {**target, **data}, applies,
            ("PASS" if ok else "FAIL") if applies else "NOT_CHECKED",
            None if applies and ok else detail,
        ))

    same_version = search["DATA_VERSION"] == runtime["version"]
    checks.append(check_record("DATA_VERSION", target, True, "PASS" if same_version else "NOT_CHECKED",
                               None if same_version else "검색 당시 자료 버전을 사용할 수 없습니다."))
    if not same_version:
        return checks

    name_key = "ATT_DIS_NM" if is_disease else "PRESP_NM"
    add("SEARCH_RANGE", any(row["DIS_UNIQN"] == disease_id for row in runtime["diseases"]),
        "선택 병증이 검색 범위에 없습니다.", diseaseId=disease_id)
    add("REGISTERED_ITEM", source is not None and source[name_key] == candidate["name"],
        "등록 항목과 저장된 후보가 일치하지 않습니다.")

    keyword_applies = is_disease and candidate.get("_trace", {}).get("keywordRank") is not None
    terms = candidate.get('_trace', {}).get('affirmedTerms', [search['INPUT_TEXT']])
    add("EXPRESSION_DISEASE", any(row["DIS_UNIQN"] == disease_id and row["term"].strip() in terms
                                 for row in runtime["keywords"]) if keyword_applies else False,
        "키워드 경로가 없거나 등록 표현과 병증 관계를 확인할 수 없습니다.",
        applies=keyword_applies, diseaseId=disease_id)
    add("DISEASE_PRESCRIPTION",
        not is_disease and disease_id in links.get(("prescription", item_id, "disease"), ())
        and any(row["DIS_UNIQN"] == disease_id and row["PRESP_UNIQN"] == item_id for row in runtime["relations"]),
        "병증과 처방의 기업 원본 관계가 일치하지 않습니다.", applies=not is_disease, diseaseId=disease_id)

    registered = {(row["compositionId"], row["id"]) for row in compositions.get(item_id, ())} if not is_disease else set()
    ingredients = {(row["compositionId"], row["id"]) for row in candidate.get("ingredients", [])}
    add("PRESCRIPTION_HERB", ingredients == registered, "처방과 약재 구성의 기업 원본 관계가 일치하지 않습니다.",
        applies=not is_disease, compositionIds=sorted(row[0] for row in ingredients))
    add("HERB_EFFICACY", False, "이번 설명 요청은 약재 효능을 근거로 사용하지 않습니다.", applies=False)
    for evidence in candidate["_sources"][:3]:
        origin = source["source"] if source else {}
        column = evidence["column"]
        cell = origin.get("cells", {}).get(column)
        add("EVIDENCE_ORIGIN",
            bool(cell and source.get(column) == evidence["originalText"]
                 and evidence["itemId"] == item_id and evidence["row"] == origin["row"]
                 and evidence["sheet"] == origin["sheet"] and evidence["fileName"] == origin["file"]
                 and evidence["sourceLocation"] == f"{origin['sheet']}!{cell}"
                 and evidence["dataVersion"] == f"sha256:{origin['file_sha256']}"
                 and evidence["excerpt"] in evidence["originalText"]),
            "저장 근거와 기업 원문의 내용·위치·버전이 일치하지 않습니다.", sourceId=evidence["sourceId"])
    return checks
