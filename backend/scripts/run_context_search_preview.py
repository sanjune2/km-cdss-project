"""문장 하나의 정규화·문맥·분기·검색 통합 실험. 서비스 API·DB는 변경하지 않는다."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.ai import context_classification_two_stage_context_v3 as classifier
from backend.ai import text_normalization, normalized_matching, context_candidate_policy
from backend.ai import search, embedding
from backend.scripts.load_search_data import read_jsonl, check_vector_contents, check_npy_matrix

PREVIEW_VERSION = "context_search_single_input_preview_v1"


def fingerprint(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def route_mentions(mentions):
    positive = [m for m in mentions if m["candidate_policy_status"] == "ACCEPT_KEYWORD_SUPPORT"]
    review = [m for m in mentions if m["candidate_policy_status"].startswith("REVIEW_")]
    if review:
        route, message = "CONFIRM_INTERPRETATION", "증상 표현의 의미나 존재 여부를 확인해주세요."
    elif not positive:
        route, message = "REVIEW_INPUT", "현재 분석 범위에서 후보 검토에 사용할 증상을 확인하기 어렵습니다. 증상 표현을 확인해주세요."
    else:
        route, message = "CANDIDATE_REVIEW", "분석된 증상 표현과 검색 후보의 근거를 함께 검토해주세요."
    return route, message, review


def load_data(root):
    paths = {
        "diseases": root / "stage1/검색용/병증원문.jsonl",
        "keywords": root / "stage1/검색용/키워드검색항목.jsonl",
        "chunks": root / "stage2/청킹결과.jsonl",
        "embeddings": root / "stage2/임베딩결과.jsonl",
        "matrix": root / "stage2/벡터행렬.npy",
    }
    fingerprints = {k: fingerprint(p) for k, p in paths.items()}
    diseases, keywords, chunks, vectors = (read_jsonl(paths[k]) for k in ["diseases", "keywords", "chunks", "embeddings"])
    names = {d["DIS_UNIQN"]: d["ATT_DIS_NM"] for d in diseases}
    if len(names) != len(diseases) or len({k["term_id"] for k in keywords}) != len(keywords):
        raise ValueError("병증 또는 키워드 식별번호가 중복됐습니다.")
    if any(type(k["DIS_UNIQN"]) is not int or k["DIS_UNIQN"] not in names for k in keywords):
        raise ValueError("등록 키워드의 연결 병증이 없습니다.")
    by_chunk = {v["chunk_id"]: v for v in vectors}
    if (len(by_chunk) != len(vectors) or len(chunks) != len(vectors)
            or {c["chunk_id"] for c in chunks} != set(by_chunk)
            or {c["embedding_row"] for c in chunks} != set(range(len(vectors)))):
        raise ValueError("원문 조각과 벡터 행의 연결이 올바르지 않습니다.")
    by_disease = {d["DIS_UNIQN"]: d for d in diseases}
    for chunk in chunks:
        vector = by_chunk[chunk["chunk_id"]]
        if any(chunk[k] != vector[k] for k in ["document_id", "entity_type", "entity_id", "embedding_row"]):
            raise ValueError("원문 조각과 벡터의 연결 정보가 다릅니다.")
        if chunk["entity_type"] == "disease":
            if chunk["entity_id"] not in by_disease:
                raise ValueError("원문 조각에 연결된 병증이 없습니다.")
            original = by_disease[chunk["entity_id"]]["semantic_text"]
            if (hashlib.sha256(original.encode("utf-8")).hexdigest() != chunk["original_text_sha256"]
                    or original[chunk["source_start"]:chunk["source_end"]] != chunk["text"]):
                raise ValueError("병증 원문과 근거 조각의 내용 또는 위치가 다릅니다.")
    check_vector_contents(chunks, vectors)
    check_npy_matrix(paths["matrix"], vectors)
    return {
        "fingerprints": fingerprints, "diseases": diseases, "keywords": keywords,
        "names": names, "chunks": chunks,
        "matrix": np.load(paths["matrix"], allow_pickle=False),
    }


def run_preview(report, data, base_url, progress):
    if classifier.PROMPT_VERSION != "mention_context_two_stage_kiwi_context_v3" or classifier.THINKING_ENABLED is not False:
        raise ValueError("검증한 문맥 v3와 사고 모드 끄기 설정을 사용해주세요.")
    if context_candidate_policy.POLICY_VERSION != "affirmed_keyword_support_review_uncertain_v1":
        raise ValueError("검증한 후보 연결 정책과 다릅니다.")
    if search.MAX_KEYWORD_CANDIDATES != context_candidate_policy.MAX_KEYWORD_CANDIDATES:
        raise ValueError("검색 후보 상한이 다릅니다.")
    text = report["symptoms"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("증상을 입력해주세요.")
    normalizer = text_normalization.KiwiTextNormalizer()
    terms = sorted({k["term"].strip() for k in data["keywords"]})
    term_results = [{"term": term, **normalizer.analyze(term)} for term in terms]
    links = [{"term_id": k["term_id"], "term": k["term"].strip(), "term_type": k["term_type"],
              "disease_id": k["DIS_UNIQN"]} for k in data["keywords"]]
    index = normalized_matching.build_keyword_index(term_results, links)
    if index["skipped_links"]:
        raise ValueError("비교에서 제외된 등록 표현이 있습니다. 정규화 자료를 확인해주세요.")
    analysis = normalizer.analyze(text)
    matches = normalized_matching.find_normalized_matches(text, analysis, index)
    for match in matches:
        match["disease_name"] = data["names"][match["disease_id"]]
    case = {"case_id": report["case_id"], "input_text": text, "keyword_matches": matches}
    mentions = classifier.prepare_mentions(case)
    report["normalization"] = {
        "policy_version": text_normalization.POLICY_VERSION,
        "registered_term_count": len(terms), "indexed_keyword_links": index["indexed_link_count"],
        "analysis": analysis, "matched_spans": len(mentions), "mapped_links": len(matches),
    }
    report["stage"] = "NORMALIZATION_COMPLETED"
    progress(report)
    if mentions:
        tags = classifier.ollama_json(base_url, "/api/tags")
        model = next((m for m in tags["models"] if m["name"] == "gemma4:e4b"), None)
        if model is None:
            raise ValueError("로컬 Ollama에 gemma4:e4b가 없습니다. 자동 설치는 하지 않습니다.")
        details = classifier.ollama_json(base_url, "/api/show", {"model": "gemma4:e4b"})
        if "completion" not in details.get("capabilities", []) or False not in details.get("thinking", {}).get("values", []):
            raise ValueError("모델 생성 기능 또는 사고 모드 끄기 지원을 확인하지 못했습니다.")
        report["context_model"] = model
        report["server_version"] = classifier.ollama_json(base_url, "/api/version")["version"]
        report["stage"] = "CONTEXT_RUNNING"
        progress(report)
        try:
            classified = classifier.classify_case(case, mentions, base_url, "gemma4:e4b")
        except classifier.ContextRunError as error:
            report["context_trace"] = error.raw_response
            report["generation_calls"] = len(error.raw_response.get("stages", []))
            raise
        report["context_run_status"] = "COMPLETED"
        report["context_trace"] = classified["raw_response"]
        report["generation_calls"] = len(classified["raw_response"]["stages"])
        case.update(classified)
    else:
        case.update(status="STRUCTURE_VALID", model_input={"input_text": text, "mentions": []}, mentions=[])
        report["context_run_status"] = "SKIPPED_NO_REGISTERED_MATCH"
        report["context_trace"] = {"stages": []}
    report["stage"] = "CONTEXT_COMPLETED"
    progress(report)
    bridge = context_candidate_policy.partition_context_case(case, data["names"])
    route, message, review = route_mentions(bridge["mentions"])
    report["classification"] = {"mentions": case["mentions"], "keyword_matches": case["keyword_matches"]}
    report["candidate_policy"] = bridge
    report["route"] = route
    report["message"] = message
    report["reviewMentions"] = review
    report["stage"] = "ROUTING_COMPLETED"
    progress(report)
    if route == "CANDIDATE_REVIEW":
        report["stage"] = "SEARCH_RUNNING"
        progress(report)
        embedder = embedding.E5Embedder()
        query = embedder.encode_query(text)
        report["query_embedding_calls"] = 1
        semantic = search.search_semantic(query, data["diseases"], data["chunks"], data["matrix"])
        ranked = search.fuse_rrf(bridge["contextKeywordIds"], [r["id"] for r in semantic], data["diseases"])
        report["queryVector"] = query.tolist()
        report["semanticCandidates"] = semantic
        semantic_by_id = {r["id"]: r for r in semantic}
        chunks_by_id = {c["chunk_id"]: c for c in data["chunks"]}
        candidates = []
        for row in ranked:
            keyword_evidence = [m for m in bridge["keyword_matches"]
                                if m["disease_id"] == row["id"] and m["candidate_policy_status"] == "ACCEPT_KEYWORD_SUPPORT"]
            semantic_evidence = None
            if row["id"] in semantic_by_id:
                sem = semantic_by_id[row["id"]]
                chunk = chunks_by_id[sem["bestChunkId"]]
                semantic_evidence = {
                    "chunkId": chunk["chunk_id"], "semanticScore": sem["semanticScore"],
                    "excerpt": chunk["text"], "sourceStart": chunk["source_start"],
                    "sourceEnd": chunk["source_end"], "source": chunk["source"],
                }
            candidates.append({**row, "keywordEvidence": keyword_evidence, "semanticEvidence": semantic_evidence})
        report["candidates"] = candidates
        report["top3"] = candidates[:3]
        report["keywordIds"] = bridge["contextKeywordIds"]
        report["search_run_status"] = "COMPLETED"
    else:
        report["search_run_status"] = "SKIPPED_INPUT_CONFIRMATION"
    report["stage"] = "COMPLETED"
    report["status"] = "COMPLETED"
    progress(report)


def main():
    parser = argparse.ArgumentParser(description="단일 문장 문맥 검색 통합 미리보기")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--symptoms", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", default="LIVE-001")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")
    if not args.symptoms.strip():
        parser.error("증상을 입력해주세요.")
    data = load_data(args.data_root)
    report = {
        "report_version": PREVIEW_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "case_id": args.case_id, "symptoms": args.symptoms,
        "status": "NOT_RUN", "stage": "DATA_VALIDATED", "used_in_search": False,
        "actual_api_modified": False, "is_final_recommendation": False,
        "temporality_evaluated": False, "criteria_used_for_inference": False,
        "generation_calls": 0, "query_embedding_calls": 0,
        "context_run_status": "NOT_RUN", "search_run_status": "NOT_RUN",
        "candidates": [], "top3": [], "keywordIds": [], "semanticCandidates": [],
        "data": data["fingerprints"], "script": fingerprint(__file__),
        "modules": {m.__name__: fingerprint(m.__file__) for m in [classifier, text_normalization, normalized_matching, context_candidate_policy, search, embedding]},
        "settings": {
            "context_prompt_version": classifier.PROMPT_VERSION, "context_schema": classifier.SCHEMA_VERSION,
            "context_options": classifier.OPTIONS, "think": classifier.THINKING_ENABLED,
            "context_prompts": classifier.STAGE_PROMPTS, "case_timeout_seconds": 60,
            "embedding_model": embedding.MODEL_ID, "embedding_revision": embedding.MODEL_REVISION,
            "rrf_k": search.RRF_K, "keyword_rrf_weight": float(search.KEYWORD_RRF_WEIGHT),
            "semantic_rrf_weight": 1.0, "semantic_query": "UNCHANGED_ORIGINAL_TEXT",
            "corpus_reembedded": False,
        },
        "notes": [
            "후보 검토 경로에서만 의미 검색과 RRF를 수행한다. 입력 확인 경로에서는 검색 호출을 생략한다.",
            "긍정 등록 표현의 부재는 환자의 증상 부재를 뜻하지 않는다. 미등록 표현은 입력 확인이 필요하다.",
            "긍정은 과거 언급도 포함한다. 현재 증상 확정과 임상 적합성 판단은 수행하지 않는다.",
            "의미 검색은 부정 표현이 포함된 원문 그대로 수행하므로 후보별 근거 적합성은 별도 검토가 필요하다.",
            "새 통합 실험이며 기존 API·DB·저장 결과를 변경하지 않는다.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        last_stage = None
        def save(current):
            nonlocal last_stage
            file.seek(0)
            file.write(json.dumps(current, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            file.truncate()
            file.flush()
            if current["stage"] != last_stage:
                print("단계:", current["stage"], flush=True)
                last_stage = current["stage"]
        save(report)
        try:
            run_preview(report, data, args.base_url, save)
            for ref in data["fingerprints"].values():
                if fingerprint(ref["path"])["sha256"] != ref["sha256"]:
                    raise ValueError("실행 중 등록 자료가 변경됐습니다.")
        except KeyboardInterrupt:
            report.update(status="INCOMPLETE", error="사용자가 실행을 중단했습니다.")
        except Exception as error:
            report.update(status="INCOMPLETE", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            save(report)
    if json.loads(args.output.read_text(encoding="utf-8")) != report:
        raise ValueError("저장된 통합 실험 결과가 다릅니다.")
    if report["status"] != "COMPLETED":
        raise SystemExit(1)
    print("처리 경로:", report["route"])
    print("생성 모델 호출:", report["generation_calls"], "/ 입력 임베딩:", report["query_embedding_calls"])
    print("후보:", len(report["candidates"]), "/ 검토 표현:", len(report["reviewMentions"]))
    for row in report["top3"]:
        print(row["rank"], row["id"], row["name"], row["score"])
    print("안내:", report["message"])
    print("저장 완료:", args.output)


if __name__ == "__main__":
    main()
