import re


# 문장 안에서 찾을 기업 등록 증상 표현의 초기 실험 목록
SENTENCE_SYMPTOM_TERMS = frozenset({
    "가래침",
    "구역",
    "구토",
    "기침",
    "답답",
    "답답함",
    "더부룩함",
    "동통",
    "두통",
    "머리앓이",
    "배앓이",
    "복통",
    "설사",
    "소화불량",
    "어지럼",
    "어질증",
    "욕지기",
    "위완통",
    "위통",
    "통증",
    "현기증",
})


def allows_sentence_match(keyword: dict) -> bool:
    """등록 표현을 문장 내 포함 검색에 사용할지 판단한다."""
    term = keyword["term"].strip()

    # 한 글자 표현은 긴 문장 안의 포함 검색에 사용하지 않는다.
    if len(term) < 2:
        return False

    # 기존에 준비한 원문 대조 일상어 연결을 사용한다.
    if keyword["term_type"] == "existing_expression":
        return True

    # 기업 키워드는 초기 실험 목록에 있는 표현만 사용한다.
    return (
        keyword["term_type"] == "corporate_keyword"
        and term in SENTENCE_SYMPTOM_TERMS
    )


# 이번 초기 실험에서 인식할 명확한 부정 표현
_EXPLICIT_NEGATION_PATTERN = re.compile(
    r"^\s*(?:함)?\s*"
    r"(?:(?:은|는|이|가|도|을|를)\s*)?"
    r"(?:(?:전혀|아예)\s*)?"
    r"(?:없어요|없습니다|없음|없다|없고|"
    r"안\s*해요|안\s*합니다|안\s*나요|"
    r"하지\s*않아요|하지\s*않습니다|"
    r"나지\s*않아요|나오지\s*않아요)"
    r"(?=$|[\s.,!?;:，。！？])"
)


def has_non_negated_match(text: str, term: str) -> bool:
    """일치한 표현의 앞뒤에 있는 초기 부정 표현을 확인한다."""
    term = term.strip()
    if not term:
        return False

    for match in re.finditer(re.escape(term), text):
        prefix = text[:match.start()]
        tail = text[match.end():]

        # 일치한 표현 바로 앞의 '안', '못'을 확인한다.
        if re.search(r"(?<!\w)(?:안|못)\s*$", prefix):
            continue

        # 일치한 표현 뒤의 기존 부정 규칙도 유지한다.
        if _EXPLICIT_NEGATION_PATTERN.match(tail) is not None:
            continue

        return True

    return False


# 초기 실험: 지정한 등록 표현의 네 가지 활용형만 사용한다.
INFLECTED_SYMPTOM_FORMS = {
    "더부룩함": (
        "더부룩해요",
        "더부룩합니다",
        "더부룩하고",
        "더부룩해서",
    ),
    "답답함": (
        "답답해요",
        "답답합니다",
        "답답하고",
        "답답해서",
    ),
}


def has_inflected_match(text: str, term: str) -> bool:
    """지정한 두 등록 표현의 활용형만 확인한다."""
    for form in INFLECTED_SYMPTOM_FORMS.get(term.strip(), ()):
        pattern = (
            r"(?<!\w)"
            + re.escape(form)
            + r"(?=$|[\s.,!?;:，。！？])"
        )

        for match in re.finditer(pattern, text):
            prefix = text[:match.start()]
            tail = text[match.end():]

            # 바로 앞에 붙은 '안', '못'은 제외한다.
            if re.search(r"(?<!\w)(?:안|못)\s*$", prefix):
                continue

            # 기존 초기 부정 규칙도 적용한다.
            if _EXPLICIT_NEGATION_PATTERN.match(tail) is not None:
                continue

            return True

    return False