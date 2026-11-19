
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import text
from database import engine

data_file = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "prescription_catalog"
    / "처방약재구성전체.jsonl"
)

columns = [
    "RSHIP_UNIQN",
    "PRESP_UNIQN",
    "MED_UNIQN",
    "MED_SPEC_REP",
    "UNT",
    "UNT_COEFF",
    "CC_INFO",
]

records = []
seen_ids = set()

with data_file.open("r", encoding="utf-8-sig") as file:
    for line_number, line in enumerate(file, start=1):
        if not line.strip():
            continue

        item = json.loads(line)

        rship_id = item.get("RSHIP_UNIQN")

        if rship_id is None or rship_id in seen_ids:
            raise ValueError(
                f"{line_number}번째 줄: 중복 또는 누락된 연결 ID"
            )

        seen_ids.add(rship_id)

        record = {
            column: item.get(column)
            for column in columns
        }

        if record["PRESP_UNIQN"] is None or record["MED_UNIQN"] is None:
            raise ValueError(
                f"{line_number}번째 줄: 처방 또는 약재 ID 누락"
            )

        if record["UNT_COEFF"] not in (None, ""):
            try:
                record["UNT_COEFF"] = Decimal(str(record["UNT_COEFF"]))
            except InvalidOperation:
                raise ValueError(
                    f"{line_number}번째 줄: 약재 수량 형식 오류"
                )
        else:
            record["UNT_COEFF"] = None

        records.append(record)

insert_sql = text("""
    INSERT INTO "PRESP_MED_RSHIP" (
        "RSHIP_UNIQN",
        "PRESP_UNIQN",
        "MED_UNIQN",
        "MED_SPEC_REP",
        "UNT",
        "UNT_COEFF",
        "CC_INFO"
    )
    VALUES (
        :RSHIP_UNIQN,
        :PRESP_UNIQN,
        :MED_UNIQN,
        :MED_SPEC_REP,
        :UNT,
        :UNT_COEFF,
        :CC_INFO
    )
""")

with engine.begin() as connection:
    existing_count = connection.execute(
        text('SELECT COUNT(*) FROM "PRESP_MED_RSHIP"')
    ).scalar_one()

    if existing_count != 0:
        raise RuntimeError(
            f"PRESP_MED_RSHIP 테이블에 이미 {existing_count}건이 있습니다. "
            "중복 적재를 방지하기 위해 중단합니다."
        )

    # 연결 대상인 처방과 약재가 모두 존재하는지 확인
    presp_ids = set(
        connection.execute(
            text('SELECT "PRESP_UNIQN" FROM "PRESP"')
        ).scalars()
    )

    med_ids = set(
        connection.execute(
            text('SELECT "MED_UNIQN" FROM "MED"')
        ).scalars()
    )

    for record in records:
        if record["PRESP_UNIQN"] not in presp_ids:
            raise ValueError(
                f"존재하지 않는 처방 ID: {record['PRESP_UNIQN']}"
            )

        if record["MED_UNIQN"] not in med_ids:
            raise ValueError(
                f"존재하지 않는 약재 ID: {record['MED_UNIQN']}"
            )

    # 모든 데이터 검증 후 적재
    for start in range(0, len(records), 500):
        batch = records[start:start + 500]
        connection.execute(insert_sql, batch)

    saved_count = connection.execute(
        text('SELECT COUNT(*) FROM "PRESP_MED_RSHIP"')
    ).scalar_one()

    if saved_count != len(records):
        raise RuntimeError(
            f"저장 건수 불일치: {saved_count}"
        )

print(f"처방-약재 연결 데이터 적재 완료: {saved_count:,}건")
