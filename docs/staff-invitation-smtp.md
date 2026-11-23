# 직원 초대 이메일 설정

백엔드의 로컬 `.env`에 발신 SMTP와 직원이 접속할 프런트엔드 주소를 설정한 후 백엔드를 재시작합니다.

```dotenv
HANUI_PUBLIC_URL=https://hanui.example.com
HANUI_SMTP_HOST=smtp.example.com
HANUI_SMTP_PORT=465
HANUI_SMTP_SECURITY=ssl
HANUI_SMTP_FROM=invites@example.com
HANUI_SMTP_USER=invites@example.com
HANUI_SMTP_PASSWORD=
```

실제 접속 정보로 바꾸세요. SMTP 공급자가 STARTTLS를 사용하면 `HANUI_SMTP_SECURITY=starttls`와 해당 포트를 사용합니다. 비밀번호는 로컬 환경 변수나 비공개 설정으로 입력합니다.

`http://localhost:5173` 링크는 같은 PC에서만 열 수 있습니다. 팀 테스트에서는 수신자 PC에서 접속 가능한 프런트엔드 주소를 사용합니다.

원장이 초대를 생성하면 초대 레코드를 저장한 뒤 이메일 발송을 시도합니다. SMTP 미설정 또는 실패 시에도 화면에서 링크를 복사할 수 있습니다. 기존 유효 초대에는 재발송하지 않으므로 새 초대의 발송을 검사할 때는 최근 초대 이력이 없는 테스트 주소를 사용합니다.

가입 링크는 기존 `/staff/register` 화면과 가입 API를 사용합니다. 초대에 지정한 직무가 적용되며 가입 신청 후 원장 승인이 필요합니다. 기존 DB의 `INVITATION`과 `ACCOUNT`을 사용하며 이 변경으로 추가할 마이그레이션은 없습니다.
