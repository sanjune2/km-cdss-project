
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from main import app


@app.get("/api/test-db-error")
def test_db_error():
    raise SQLAlchemyError("DB 오류 테스트")


client = TestClient(app)

response = client.get("/api/test-db-error")

print("상태 코드:", response.status_code)
print("응답 내용:", response.json())

assert response.status_code == 503
assert response.json() == {
    "detail": "데이터베이스 처리 중 오류가 발생했습니다."
}

print("공통 DB 예외 처리 테스트 성공!")
