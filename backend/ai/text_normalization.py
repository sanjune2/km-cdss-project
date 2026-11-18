from kiwipiepy import Kiwi


POLICY_VERSION = "kiwi_split_complex_units_v1"

KIWI_SETTINGS = {
    "num_workers": 1,
    "model_type": "cong",
    "load_default_dict": True,
    "integrate_allomorph": True,
}

BOUNDARY_TAGS = frozenset({
    "SF", "SP", "SS", "SSO", "SSC", "SO", "SW",
})


class KiwiTextNormalizer:
    def __init__(self) -> None:
        self.kiwi = Kiwi(**KIWI_SETTINGS)

    def analyze(self, text: str) -> dict:
        if not isinstance(text, str):
            raise ValueError("분석할 입력은 문자열이어야 합니다.")

        tokens = []
        units = []
        segment = 0

        for token in self.kiwi.tokenize(text, split_complex=True):
            base_tag = token.tag.split("-")[0]
            token_index = len(tokens)
            tokens.append({
                "form": token.form,
                "tag": token.tag,
                "base_tag": base_tag,
                "start": token.start,
                "length": token.len,
            })

            if base_tag in BOUNDARY_TAGS:
                segment += 1
                continue

            # 조사·어미만 대조용 목록에서 제외하고 원시 tokens는 보존한다.
            # 안·않·없 등의 단어와 원문 위치를 일괄 삭제하지 않는다.
            if base_tag.startswith(("J", "E")):
                continue

            units.append({
                "form": token.form,
                "tag": base_tag,
                "token_index": token_index,
                "segment": segment,
            })

        return {
            "tokens": tokens,
            "search_units": units,
        }

