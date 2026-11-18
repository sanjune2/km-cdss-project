"""문맥 기반 키워드 후보의 RRF 결합 비교. 기존 검색 API에는 연결하지 않는다."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.ai import embedding, search, keyword_rules, context_candidate_policy
from backend.scripts.load_search_data import read_jsonl, check_vector_contents, check_npy_matrix


def fingerprint(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require_fingerprint(ref):
    if fingerprint(ref["path"])["sha256"] != ref["sha256"]:
        raise ValueError(f"비교 기준이 저장 이후 변경됐습니다: {ref['path']}")


def combine_case(case, semantic_candidates, diseases):
    variants = {}
    semantic_ids = [row["id"] for row in semantic_candidates]
    for label, field in (("legacy", "legacyKeywordIds"),
                         ("normalized", "normalizedKeywordIds"),
                         ("context", "contextKeywordIds")):
        variants[label] = {
            "keywordIds": case[field],
            "candidates": search.fuse_rrf(case[field], semantic_ids, diseases),
        }
    ranks = {label: {row["id"]: row["rank"] for row in result["candidates"]}
             for label, result in variants.items()}
    names = {d["DIS_UNIQN"]: d["ATT_DIS_NM"] for d in diseases}
    all_ids = set().union(*(set(value) for value in ranks.values()))
    changes = [
        {"id": item, "name": names[item],
         "legacyRank": ranks["legacy"].get(item),
         "normalizedRank": ranks["normalized"].get(item),
         "contextRank": ranks["context"].get(item)}
        for item in sorted(all_ids, key=lambda item: (
            ranks["context"].get(item, len(all_ids) + 1), names[item], item))
        if len({ranks[label].get(item) for label in ranks}) > 1
    ]
    ignored = {m["disease_id"] for m in case["keyword_matches"]
               if m["candidate_policy_status"] != "ACCEPT_KEYWORD_SUPPORT"}
    no_positive_support = ignored - set(case["allContextKeywordIds"])
    review_spans = [m for m in case["mentions"]
                    if m["candidate_policy_status"].startswith("REVIEW_")]
    return {
        "variants": variants, "rankChanges": changes,
        "hasAffirmedKeywordSupport": bool(case["contextKeywordIds"]),
        "reviewMentions": review_spans,
        "contextTop3WithoutAffirmedKeywordSupport": [
            {"id": row["id"], "name": row["name"], "rank": row["rank"]}
            for row in variants["context"]["candidates"][:3]
            if row["id"] in no_positive_support
        ],
        "used_in_search": False,
    }


def update_summary(report):
    completed = [c for c in report["cases"] if c["status"] == "COMPLETED"]
    def ids(case, variant, count=None):
        rows = case["variants"][variant]["candidates"]
        return [row["id"] for row in (rows if count is None else rows[:count])]
    report["summary"] = {
        "selected_cases": len(report["cases"]), "completed_cases": len(completed),
        "incomplete_cases": sum(c["status"] == "INCOMPLETE" for c in report["cases"]),
        "not_run_cases": sum(c["status"] == "NOT_RUN" for c in report["cases"]),
        "query_embedding_calls": report["query_embedding_calls"],
        "cases_top3_changed_by_normalization": sum(ids(c, "legacy", 3) != ids(c, "normalized", 3) for c in completed),
        "cases_top3_changed_by_context": sum(ids(c, "normalized", 3) != ids(c, "context", 3) for c in completed),
        "cases_top3_changed_vs_legacy": sum(ids(c, "legacy", 3) != ids(c, "context", 3) for c in completed),
        "cases_without_affirmed_keyword_support": sum(not c["hasAffirmedKeywordSupport"] for c in completed),
        "cases_with_review_mentions": sum(bool(c["reviewMentions"]) for c in completed),
        "cases_context_top3_contains_unsupported_linked_disease": sum(bool(c["contextTop3WithoutAffirmedKeywordSupport"]) for c in completed),
        "quality_evaluation": "NOT_EVALUATED_NO_DISEASE_GOLD",
    }


def main():
    parser = argparse.ArgumentParser(description="같은 의미 검색을 유지한 키워드 후보·RRF 결합 비교")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")
    source = json.loads(args.candidates.read_text(encoding="utf-8"))
    if (source["report_version"] != "context_keyword_candidate_bridge_v1"
            or source["used_in_search"] is not False
            or source["policy_version"] != context_candidate_policy.POLICY_VERSION):
        raise ValueError("이번 비교에 사용할 후보 연결 결과가 아닙니다.")
    for field in ["disease_source", "keyword_source", "legacy_search_script", "legacy_keyword_rules_script", "policy_script", "script"]:
        require_fingerprint(source[field])
    for field, module in [("legacy_search_script", search), ("legacy_keyword_rules_script", keyword_rules), ("policy_script", context_candidate_policy)]:
        if fingerprint(module.__file__)["sha256"] != source[field]["sha256"]:
            raise ValueError("현재 코드가 후보 비교 실행 당시와 다릅니다.")
    for item in source["sources"]:
        require_fingerprint(item["report"])
        require_fingerprint(item["source_match_report"])
    root = args.data_root
    paths = {
        "diseases": root / "stage1/검색용/병증원문.jsonl",
        "keywords": root / "stage1/검색용/키워드검색항목.jsonl",
        "chunks": root / "stage2/청킹결과.jsonl",
        "embeddings": root / "stage2/임베딩결과.jsonl",
        "matrix": root / "stage2/벡터행렬.npy",
    }
    data_fingerprints = {k: fingerprint(p) for k, p in paths.items()}
    if (data_fingerprints["diseases"]["sha256"] != source["disease_source"]["sha256"]
            or data_fingerprints["keywords"]["sha256"] != source["keyword_source"]["sha256"]):
        raise ValueError("현재 데이터 폴더와 후보 연결 결과의 등록 자료가 다릅니다.")
    diseases, keywords, chunks, embeddings = (read_jsonl(paths[k]) for k in ["diseases", "keywords", "chunks", "embeddings"])
    names = {row["DIS_UNIQN"]: row["ATT_DIS_NM"] for row in diseases}
    if len(names) != len(diseases):
        raise ValueError("병증 식별번호가 중복됐습니다.")
    if len(chunks) != len(embeddings) or len({c["chunk_id"] for c in chunks}) != len(chunks):
        raise ValueError("원문 조각과 벡터 메타데이터의 연결을 확인해주세요.")
    by_chunk = {row["chunk_id"]: row for row in embeddings}
    if len(by_chunk) != len(embeddings) or set(by_chunk) != {c["chunk_id"] for c in chunks}:
        raise ValueError("조각과 벡터의 식별번호가 다릅니다.")
    if {c["embedding_row"] for c in chunks} != set(range(len(embeddings))):
        raise ValueError("조각의 벡터 행번호가 누락 또는 중복됐습니다.")
    for chunk in chunks:
        vector = by_chunk[chunk["chunk_id"]]
        for key in ["document_id", "entity_type", "entity_id", "embedding_row"]:
            if chunk[key] != vector[key]:
                raise ValueError("조각과 벡터의 연결 정보가 다릅니다.")
    check_vector_contents(chunks, embeddings)
    check_npy_matrix(paths["matrix"], embeddings)
    matrix = np.load(paths["matrix"], allow_pickle=False)
    if len({c["case_id"] for c in source["cases"]}) != len(source["cases"]):
        raise ValueError("후보 결과의 사례 식별번호가 중복됐습니다.")
    for case in source["cases"]:
        if search.search_keywords(case["input_text"], diseases, keywords) != case["legacyKeywordIds"]:
            raise ValueError("기존 키워드 검색이 후보 비교 결과와 다릅니다.")
        expected_raw = {row["disease_id"] for row in case["keyword_matches"]}
        expected_context = {row["disease_id"] for row in case["keyword_matches"]
                            if row["candidate_policy_status"] == "ACCEPT_KEYWORD_SUPPORT"}
        order = lambda values: sorted(values, key=lambda i: (names[i], i))
        if (case["allNormalizedKeywordIds"] != order(expected_raw)
                or case["allContextKeywordIds"] != order(expected_context)
                or case["normalizedKeywordIds"] != order(expected_raw)[:search.MAX_KEYWORD_CANDIDATES]
                or case["contextKeywordIds"] != order(expected_context)[:search.MAX_KEYWORD_CANDIDATES]):
            raise ValueError("키워드 연결 기록과 후보 목록이 다릅니다.")
    report = {
        "report_version": "context_hybrid_shadow_v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "source_candidates": fingerprint(args.candidates), "data": data_fingerprints,
        "script": fingerprint(__file__), "search_script": fingerprint(search.__file__),
        "embedding_script": fingerprint(embedding.__file__),
        "settings": {
            "model_id": embedding.MODEL_ID, "model_revision": embedding.MODEL_REVISION,
            "query_input": "UNCHANGED_ORIGINAL_TEXT", "semantic_shared_across_variants": True,
            "query_vector_saved_for_replay": True,
            "rrf_k": search.RRF_K, "keyword_rrf_weight": float(search.KEYWORD_RRF_WEIGHT),
            "semantic_rrf_weight": 1.0, "keyword_rank_policy": "all_tied_first",
            "max_keyword_candidates": search.MAX_KEYWORD_CANDIDATES,
            "max_semantic_candidates": search.MAX_SEMANTIC_CANDIDATES,
            "production_search_modified": False, "corpus_reembedded": False,
        },
        "used_in_search": False, "live_generation_model_calls": 0,
        "criteria_used_for_inference": False, "query_embedding_calls": 0,
        "initialization_status": "NOT_RUN",
        "notes": [
            "문맥 판단은 키워드 가산에만 반영한다. 의미 검색은 부정·불확실·일반 표현이 담긴 원문 그대로 수행한다.",
            "키워드 지지를 제거해도 같은 병증이 의미 검색으로 남을 수 있다. 이를 자동으로 부적합 병증이나 추천 확정으로 해석하지 않는다.",
            "원문 자료의 임베딩은 재생성하지 않고, 입력 문장의 벡터만 로컬 E5 모델로 계산한다.",
            "병증 정답 기준이 없는 개발 문장 비교다. 순위 변화와 검색 품질 개선은 구분한다.",
        ],
        "cases": [{"case_id": c["case_id"], "input_text": c["input_text"], "status": "NOT_RUN"} for c in source["cases"]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        def save():
            update_summary(report)
            file.seek(0)
            file.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            file.truncate()
            file.flush()
        save()
        active = None
        try:
            embedder = embedding.E5Embedder()
            report["initialization_status"] = "COMPLETED"
            for number, case in enumerate(source["cases"], start=1):
                active = report["cases"][number - 1]
                active["status"] = "RUNNING"
                save()
                started = time.monotonic()
                vector = embedder.encode_query(case["input_text"])
                report["query_embedding_calls"] += 1
                semantic = search.search_semantic(vector, diseases, chunks, matrix)
                active.update(combine_case(case, semantic, diseases))
                active.update(queryVector=vector.tolist(), semanticCandidates=semantic,
                              status="COMPLETED", elapsed_seconds=time.monotonic() - started)
                save()
                top3 = {label: [row["id"] for row in value["candidates"][:3]] for label, value in active["variants"].items()}
                print(f"[{number}/{len(source['cases'])}] {case['case_id']} 상위3개 {top3}", flush=True)
        except KeyboardInterrupt:
            report["interrupted"] = True
            if active is not None and active["status"] == "RUNNING":
                active.update(status="INCOMPLETE", error="사용자가 실행을 중단했습니다.")
            print("중단까지의 결과를 저장합니다.", flush=True)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            if active is not None and active["status"] == "RUNNING":
                active.update(status="INCOMPLETE", error=report["error"])
            if report["initialization_status"] == "NOT_RUN":
                report["initialization_status"] = "INCOMPLETE"
            raise
        finally:
            save()
    if json.loads(args.output.read_text(encoding="utf-8")) != report:
        raise ValueError("저장된 비교 결과가 일치하지 않습니다.")
    for ref in data_fingerprints.values():
        require_fingerprint(ref)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("저장 완료:", args.output)
    print("키워드·의미 검색 RRF 비교만 수행 / 기존 API·자료 벡터·순위 변경 없음")
    if report["summary"]["completed_cases"] != len(report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
