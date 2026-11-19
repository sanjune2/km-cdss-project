
import json
from pathlib import Path

from sqlalchemy import text
from database import engine

data_file = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "prescription_catalog"
    / "약재전체원문.jsonl"
)

columns = [
    "MED_UNIQN",
    "ORIG_CD_NM",
    "MED_NM",
    "SCIN_NM",
    "NORM_NM",
    "LTN_NM",
    "FAM_NM",
    "FMED_PRT_NM",
    "MED_APR_CONT",
    "EXTR_CONT",
    "DIFF_NM_CONT",
    "TMP_NM_CONT",
    "ACT_PRT_NM_CONT",
    "TABO_CONT",
    "MED_CD",
]

limits = {
    "ORIG_CD_NM": 20,
    "MED_NM": 50,
    "SCIN_NM": 150,
    "NORM_NM": 100,
    "LTN_NM": 100,
    "FAM_NM": 100,
    "FMED_PRT_NM": 100,
    "MED_APR_CONT": 1000,
    "EXTR_CONT": 2000,
    "DIFF_NM_CONT": 500,
    "TMP_NM_CONT": 100,
    "ACT_PRT_NM_CONT": 100,
    "TABO_CONT": 1000,
    "MED_CD": 20,
}

records = []
seen_ids = set()

with data_file.open("r", encoding="utf-8-sig") as file:
    for line_number, line in enumerate(file, start=1):
        if not line.strip():
            continue

        item = json.loads(line)
        med_id = item.get("MED_UNIQN")

        if med_id is None or med_id in seen_ids:
            raise ValueError(
                f"{line_number}번째 줄: 중복 또는 누락된 약재 ID"
            )

        seen_ids.add(med_id)

        record = {
            column: item.get(column)
            for column in columns
        }

        if not record["ORIG_CD_NM"] or not record["MED_NM"] or not record["MED_CD"]:
            raise ValueError(
                f"{line_number}번째 줄: 필수값 누락"
            )

        for column, limit in limits.items():
            value = record[column]

            if value is not None and len(str(value)) > limit:
                raise ValueError(
                    f"{line_number}번째 줄: {column} "
                    f"길이 초과 ({len(str(value))}/{limit})"
                )

        records.append(record)

insert_sql = text("""
    INSERT INTO "MED" (
        "MED_UNIQN",
        "ORIG_CD_NM",
        "MED_NM",
        "SCIN_NM",
        "NORM_NM",
        "LTN_NM",
        "FAM_NM",
        "FMED_PRT_NM",
        "MED_APR_CONT",
        "EXTR_CONT",
        "DIFF_NM_CONT",
        "TMP_NM_CONT",
        "ACT_PRT_NM_CONT",
        "TABO_CONT",
        "MED_CD"
    )
    VALUES (
        :MED_UNIQN,
        :ORIG_CD_NM,
        :MED_NM,
        :SCIN_NM,
        :NORM_NM,
        :LTN_NM,
        :FAM_NM,
        :FMED_PRT_NM,
        :MED_APR_CONT,
        :EXTR_CONT,
        :DIFF_NM_CONT,
        :TMP_NM_CONT,
        :ACT_PRT_NM_CONT,
        :TABO_CONT,
        :MED_CD
    )
""")

with engine.begin() as connection:
    existing_count = connection.execute(
        text('SELECT COUNT(*) FROM "MED"')
    ).scalar_one()

    if existing_count != 0:
        raise RuntimeError(
            f"MED 테이블에 이미 {existing_count}개가 있습니다. "
            "중복 적재를 방지하기 위해 중단합니다."
        )

    for start in range(0, len(records), 500):
        batch = records[start:start + 500]
        connection.execute(insert_sql, batch)

    saved_count = connection.execute(
        text('SELECT COUNT(*) FROM "MED"')
    ).scalar_one()

    if saved_count != len(records):
        raise RuntimeError(
            f"저장 건수 불일치: {saved_count}"
        )

print(f"약재 데이터 적재 완료: {saved_count:,}개")
