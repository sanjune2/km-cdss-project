"""Company-data search for the v1.3 service endpoints."""
import hashlib
import os
from functools import lru_cache
from pathlib import Path
from threading import Lock
from urllib.parse import quote

import numpy as np

from ai_rrf import fuse_rrf
from ai_semantic import search_semantic
from scripts.load_search_data import (
    DATA_FILES, check_chunk_links, check_npy_matrix, check_references,
    check_unique_ids, check_vector_contents, read_jsonl,
)


def explanation(evidence):
    return {
        "status": "NOT_REQUESTED" if evidence else "INCOMPLETE",
        "text": None,
        "message": None if evidence else "출처 확인을 완료하지 못해 AI 설명을 제공하지 않습니다",
        "checkedItems": [], "uncheckedItems": [], "unexplainedSymptoms": [],
    }


def evidence_response(source):
    fields = ("sourceId", "sourceTitle", "dataVersion", "fileName", "sheet",
              "column", "sourceLocation", "itemId", "row", "excerpt")
    return {**{key: source[key] for key in fields},
            "sourceUrl": "/api/ai/sources/" + quote(source["sourceId"], safe="")}


def disease_evidence(row, chunk):
    source = row["source"]
    original = row["semantic_text"]
    start, end = chunk["source_start"], chunk["source_end"]
    if (hashlib.sha256(original.encode()).hexdigest() != chunk["original_text_sha256"]
            or not 0 <= start < end <= len(original)
            or original[start:end] != chunk["text"]):
        raise ValueError("병증 검색 원문과 벡터 조각이 일치하지 않습니다.")
    column = next((key for key, cell in source["cells"].items()
                   if f"{source['sheet']}!{cell}" == row["semantic_field_origin"]), None)
    cell = source["cells"].get(column)
    # A derived semantic document alone cannot establish an Excel citation.
    if chunk["source"] != source or not cell or not isinstance(row.get(column), str) or chunk["text"] not in row[column]:
        return []
    version = source["file_sha256"]
    return [{
        "sourceId": f"DIS-{row['DIS_UNIQN']}-{column}-{version}-{start}",
        "sourceTitle": row["ATT_DIS_NM"], "dataVersion": f"sha256:{version}",
        "fileName": source["file"], "sheet": source["sheet"], "column": column,
        "sourceLocation": f"{source['sheet']}!{cell}", "itemId": row["DIS_UNIQN"],
        "row": source["row"], "excerpt": chunk["text"], "originalText": row[column],
    }]


_load_lock = Lock()


def get_runtime():
    root = Path(os.getenv("KM_CDSS_DATA_ROOT", r"C:\km-cdss-data")).resolve()
    with _load_lock:
        return load_runtime(root)


@lru_cache(maxsize=1)
def load_runtime(root):
    paths = [root / name for name in DATA_FILES]
    diseases, keywords, prescriptions, relations, chunks, embeddings = map(read_jsonl, paths)
    disease_ids = check_unique_ids(diseases, "DIS_UNIQN", "병증", int)
    if len(disease_ids) != 44:
        raise ValueError("v1.3 병증 검색 범위는 44개여야 합니다.")
    prescription_ids = check_unique_ids(prescriptions, "PRESP_UNIQN", "처방", int)
    check_references(keywords, "DIS_UNIQN", disease_ids, "검색 키워드")
    check_chunk_links(chunks, embeddings, disease_ids, prescription_ids)
    check_vector_contents(chunks, embeddings)
    matrix_path = root / "stage2/벡터행렬.npy"
    check_npy_matrix(matrix_path, embeddings)
    if {row["entity_id"] for row in chunks if row["entity_type"] == "disease"} != disease_ids:
        raise ValueError("병증 벡터 범위가 기업 검색 범위와 일치하지 않습니다.")
    digest = hashlib.sha256()
    for path in [*paths, matrix_path]:
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    from .embedding import E5Embedder, MODEL_ID, MODEL_REVISION

    return {
        "root": root, "diseases": diseases, "keywords": keywords, "prescriptions": prescriptions,
        "relations": relations, "chunks": chunks, "matrix": np.load(matrix_path, allow_pickle=False),
        "version": digest.hexdigest()[:48], "embedder": E5Embedder(),
        "versions": {
            "embeddingModel": MODEL_ID, "embeddingRevision": MODEL_REVISION,
            "chunkPolicies": sorted({row["chunk_policy_version"] for row in chunks}),
            "searchScope": "v1.3-44", "expressionLinks": digest.hexdigest()[:48],
        },
    }


def diseases_for(symptoms, data, assessment=None):
    from .symptom_context import analyze_symptoms

    assessment = assessment if assessment is not None else analyze_symptoms(symptoms, data)
    terms = assessment['affirmedTerms']
    search_terms = assessment.get('searchTerms', terms)
    if not search_terms:
        return []
    by_id = {row["DIS_UNIQN"]: row for row in data["diseases"]}
    keyword_ids = sorted(
        {row["DIS_UNIQN"] for row in data["keywords"] if row["term"].strip() in terms},
        key=lambda item_id: (by_id[item_id]["ATT_DIS_NM"], item_id),
    )[:30]
    semantic = search_semantic(
        data["embedder"].encode_query(' '.join(search_terms)), data["diseases"], data["chunks"], data["matrix"],
    )
    semantic_by_id = {row["id"]: row for row in semantic}
    chunks = {row["chunk_id"]: row for row in data["chunks"]}
    rows = fuse_rrf(keyword_ids, list(semantic_by_id), data["diseases"])
    for row in rows:
        item_id = row["id"]
        match = semantic_by_id.get(item_id)
        sources = disease_evidence(by_id[item_id], chunks[match["bestChunkId"]]) if match else []
        row["evidence"] = [evidence_response(source) for source in sources]
        row["explanation"] = explanation(sources)
        row["_sources"] = sources
        row["_trace"] = {
            "name": row["name"],
            "keywordRank": keyword_ids.index(item_id) + 1 if item_id in keyword_ids else None,
            "semantic": match,
            "affirmedTerms": terms,
        }
    return rows


@lru_cache(maxsize=1)
def load_catalog(root):
    return (
        read_jsonl(root / "처방약재구성전체.jsonl"),
        read_jsonl(root / "약재전체원문.jsonl"),
    )


def prescriptions_for(symptoms, disease_id, data, assessment=None):
    from .prescription_search import search_prescriptions
    from .symptom_context import analyze_symptoms

    assessment = assessment if assessment is not None else analyze_symptoms(symptoms, data)
    search_terms = assessment.get('searchTerms', assessment['affirmedTerms'])
    if not search_terms:
        raise ValueError('처방 검색에 사용할 현재 환자의 긍정 증상이 없습니다.')

    catalog = Path(os.getenv(
        "KM_CDSS_CATALOG_ROOT", str(Path(__file__).resolve().parents[2] / "data/prescription_catalog"),
    )).resolve()
    compositions, herbs = load_catalog(catalog)
    policy = os.getenv("KM_CDSS_PRESCRIPTION_EVALUATION_POLICY", "cosine-v1.3").strip()
    if policy not in ("", "cosine-v1.3"):
        raise ValueError("지원하지 않는 처방 평가 정책입니다.")
    result = search_prescriptions(
        ' '.join(search_terms), disease_id, data["embedder"], data["diseases"], data["prescriptions"],
        data["relations"], data["chunks"], data["matrix"], compositions, herbs,
        evaluation_configured=bool(policy),
    )
    result["_evaluationPolicy"] = policy or None
    for row in result["candidates"] + result["unscoredCandidates"]:
        sources = row.pop("evidenceSources")
        row["_sources"] = sources
        row["_cautionSources"] = row.pop("cautionSources")
        row.pop("bestChunkId", None)
        row["evidence"] = [evidence_response(source) for source in sources]
        row["explanation"] = explanation(sources)
    return result
