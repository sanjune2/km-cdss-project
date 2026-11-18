import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from kiwipiepy import Kiwi


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def fingerprint(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="형태소 분석 출력 확인")
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--keywords", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("결과 파일이 이미 있습니다. 새 파일명을 사용해주세요.")

    query_path = args.experiment_root / "queries.jsonl"
    queries = read_jsonl(query_path)
    keywords = read_jsonl(args.keywords)

    if len({row["case_id"] for row in queries}) != len(queries):
        raise ValueError("개발 입력의 식별번호가 중복됐습니다.")
    if len({row["term_id"] for row in keywords}) != len(keywords):
        raise ValueError("등록 표현의 식별번호가 중복됐습니다.")

    settings = {
        "num_workers": 1,
        "model_type": "cong",
        "load_default_dict": True,
        "integrate_allomorph": True,
    }
    kiwi = Kiwi(**settings)

    def analyze(text: str) -> list[dict]:
        return [
            {
                "form": token.form,
                "tag": token.tag,
                "start": token.start,
                "length": token.len,
            }
            for token in kiwi.tokenize(text)
        ]

    terms = sorted({row["term"].strip() for row in keywords})
    term_results = [
        {"term": term, "tokens": analyze(term)}
        for term in terms
    ]
    cases = [
        {
            "case_id": row["case_id"],
            "input_text": row["input_text"],
            "tokens": analyze(row["input_text"]),
        }
        for row in queries
    ]
    report = {
        "report_version": "kiwi_raw_analysis_v1",
        "purpose": "원시 형태소 출력 확인. 검색·부정 판정·정확도 평가 전.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "kiwipiepy_version": metadata.version("kiwipiepy"),
        "kiwipiepy_model_version": metadata.version("kiwipiepy_model"),
        "settings": settings,
        "inputs": [fingerprint(query_path), fingerprint(args.keywords)],
        "script": fingerprint(Path(__file__)),
        "summary": {
            "query_count": len(cases),
            "keyword_row_count": len(keywords),
            "unique_term_count": len(terms),
        },
        "keyword_links": [
            {
                "term_id": row["term_id"],
                "term": row["term"].strip(),
                "term_type": row["term_type"],
                "disease_id": row["DIS_UNIQN"],
            }
            for row in keywords
        ],
        "registered_terms": term_results,
        "cases": cases,
    }

    serialized = json.dumps(
        report, ensure_ascii=False, indent=2, allow_nan=False
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(serialized + "\n")

    saved = json.loads(args.output.read_text(encoding="utf-8"))
    if saved != report:
        raise ValueError("저장한 형태소 분석 결과가 일치하지 않습니다.")

    print("Kiwi 버전:", report["kiwipiepy_version"])
    print("등록 행:", len(keywords), "/ 서로 다른 표현:", len(terms))
    print("분석한 개발 입력:", len(cases), "건")
    for row in term_results:
        if row["term"] in ("더부룩함", "답답함"):
            print("등록 표현:", row["term"],
                  [(token["form"], token["tag"]) for token in row["tokens"]])
    for row in cases:
        print(row["case_id"], row["input_text"])
        print([(token["form"], token["tag"]) for token in row["tokens"]])
    print("저장 완료:", args.output)
    print("형태소 분석 출력 저장·재조회 확인 완료")


if __name__ == "__main__":
    main()

