
import getpass
import psycopg

password = getpass.getpass("PostgreSQL 비밀번호: ")

try:
    with psycopg.connect(
        host="localhost",
        port=5432,
        dbname="han_uigyeol",
        user="postgres",
        password=password
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database();")
            result = cursor.fetchone()

            print("DB 연결 성공!")
            print("연결된 데이터베이스:", result[0])

except Exception as error:
    print("DB 연결 실패:", error)
