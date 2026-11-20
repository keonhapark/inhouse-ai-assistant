"""외부로 나가는 요청의 개인정보 가림. Presidio에 한국 인식기를 더합니다.

- spaCy 언어 모델은 쓰지 않습니다. 한국어 모델은 크고 이름 인식 품질도 규칙보다 낫다고 보기 어려워, 토큰만 나누는
  빈 다국어 파이프라인(`xx`)에 정규식 인식기만 올립니다. 그래서 사람 이름처럼 규칙이 없는 형태는 잡지 못하고,
  그 몫은 평가에서 따로 잽니다.
- 문맥 낱말(예: 계좌 앞의 "은행")은 Presidio의 표제어 문맥 강화 대신 일치 위치 앞 글자 창에서 찾습니다
  (WindowContextEnhancer).
  한국어는 조사가 붙어("계좌번호는") 토큰 단위 비교가 맞지 않기 때문입니다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.context_aware_enhancers import ContextAwareEnhancer
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngine
from presidio_analyzer.predefined_recognizers import CreditCardRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

LANG = "ko"
THRESHOLD = 0.5

LABELS = {
    "KR_RRN": "[주민등록번호]",
    "KR_PHONE": "[전화번호]",
    "KR_BANK_ACCOUNT": "[계좌번호]",
    "KR_BRN": "[사업자등록번호]",
    "KR_DRIVER_LICENSE": "[운전면허번호]",
    "KR_PASSPORT": "[여권번호]",
    "EMAIL_ADDRESS": "[이메일]",
    "CREDIT_CARD": "[카드번호]",
}


class PatternOnlyNlpEngine(NlpEngine):
    """토큰만 나누고 개체 인식은 하지 않는 NLP 엔진."""

    def __init__(self) -> None:
        self._nlp = spacy.blank("xx")

    def load(self) -> None:
        pass

    def is_loaded(self) -> bool:
        return True

    def process_text(self, text: str, language: str) -> NlpArtifacts:
        doc = self._nlp(text)
        return NlpArtifacts(entities=[], tokens=doc, tokens_indices=[t.idx for t in doc],
                            lemmas=[t.text for t in doc], nlp_engine=self, language=language)

    def process_batch(self, texts, language, batch_size=1, n_process=1, **kwargs):  # pragma: no cover
        for t in texts:
            yield t, self.process_text(t, language)

    def is_stopword(self, word: str, language: str) -> bool:
        return False

    def is_punct(self, word: str, language: str) -> bool:
        return False

    def get_supported_entities(self) -> list[str]:
        return []

    def get_supported_languages(self) -> list[str]:
        return [LANG]


class _KoreanPatternRecognizer(PatternRecognizer):
    def __init__(self, entity: str, patterns: list[Pattern], context: list[str]):
        super().__init__(supported_entity=entity, patterns=patterns, context=context, supported_language=LANG)


class WindowContextEnhancer(ContextAwareEnhancer):
    """일치 앞 `window`글자 안에 인식기의 문맥 낱말이 있으면 점수를 `boost`만큼 올립니다."""

    def __init__(self, window: int = 15, boost: float = 0.4):
        super().__init__(context_similarity_factor=boost, min_score_with_context_similarity=0.0,
                         context_prefix_count=0, context_suffix_count=0)
        self.window, self.boost = window, boost

    def enhance_using_context(self, text, raw_results, nlp_artifacts, recognizers, context=None):
        words = {r.id: (r.context or []) for r in recognizers}
        out = []
        for res in raw_results:
            rid = res.recognition_metadata.get(RecognizerResult.RECOGNIZER_IDENTIFIER_KEY)
            before = text[max(0, res.start - self.window):res.start]
            if any(w in before for w in words.get(rid, [])):
                res.score = min(1.0, res.score + self.boost)
            out.append(res)
        return out


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class RrnRecognizer(_KoreanPatternRecognizer):
    """주민등록번호(외국인등록번호 포함). 생년월일이 맞아야 하고, 검증 숫자가 맞으면 확신합니다.

    2020년 10월 뒤 발급 번호는 뒷자리가 무작위라 검증 숫자가 맞지 않을 수 있어, 틀려도 버리지 않습니다.
    """

    def __init__(self) -> None:
        super().__init__("KR_RRN", [Pattern("rrn", r"(?<!\d)\d{6}(?:\s?-\s?)?[1-8]\d{6}(?!\d)", 0.6)],
                         ["주민", "등록번호", "주민번호", "외국인"])

    def validate_result(self, pattern_text: str) -> bool | None:
        d = _digits(pattern_text)
        century = {"1": 1900, "2": 1900, "5": 1900, "6": 1900, "3": 2000, "4": 2000, "7": 2000, "8": 2000}[d[6]]
        try:
            date(century + int(d[0:2]), int(d[2:4]), int(d[4:6]))
        except ValueError:
            return False
        check = (11 - sum(int(a) * b for a, b in zip(d[:12], [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5])) % 11) % 10
        return True if check == int(d[12]) else None


class BrnRecognizer(_KoreanPatternRecognizer):
    """사업자등록번호 000-00-00000. 검증 숫자가 맞을 때만 잡습니다."""

    def __init__(self) -> None:
        super().__init__("KR_BRN", [Pattern("brn", r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)", 0.5)],
                         ["사업자", "등록번호"])

    def validate_result(self, pattern_text: str) -> bool | None:
        d = [int(c) for c in _digits(pattern_text)]
        w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
        s = sum(a * b for a, b in zip(d[:9], w)) + (d[8] * 5) // 10
        return (10 - s % 10) % 10 == d[9]


def build_analyzer() -> AnalyzerEngine:
    registry = RecognizerRegistry(supported_languages=[LANG])
    registry.add_recognizer(RrnRecognizer())
    registry.add_recognizer(BrnRecognizer())
    registry.add_recognizer(_KoreanPatternRecognizer("KR_PHONE", [
        Pattern("mobile", r"(?<!\d)01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)", 0.7),
        Pattern("landline", r"(?<!\d)0(?:2|[3-6][1-5])[-.\s)]\s?\d{3,4}[-.\s]\d{4}(?!\d)", 0.6),
        Pattern("intl", r"\+82[-\s]?1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)", 0.7),
    ], ["전화", "연락처", "휴대폰", "핸드폰", "번호", "tel", "Tel"]))
    # 계좌번호는 숫자 묶음 모양이 다양해 문맥 낱말이 있어야 문턱을 넘습니다(0.3 + 0.4).
    registry.add_recognizer(_KoreanPatternRecognizer("KR_BANK_ACCOUNT", [
        Pattern("dashed", r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,7}(?:-\d{1,3})?(?!\d)", 0.3),
        Pattern("plain", r"(?<!\d)\d{10,14}(?!\d)", 0.2),
    ], ["계좌", "은행", "입금", "송금", "이체", "예금주"]))
    registry.add_recognizer(_KoreanPatternRecognizer("KR_DRIVER_LICENSE", [
        Pattern("license", r"(?<!\d)\d{2}-\d{2}-\d{6}-\d{2}(?!\d)", 0.4),
    ], ["면허", "운전"]))
    registry.add_recognizer(_KoreanPatternRecognizer("KR_PASSPORT", [
        Pattern("passport", r"(?<![A-Za-z0-9])[MSROD]\d{3}[A-Z]\d{4}(?![A-Za-z0-9])|(?<![A-Za-z0-9])[MSROD]\d{8}(?!\d)", 0.3),
    ], ["여권"]))
    # Presidio 기본 이메일 인식기는 tldextract가 첫 호출에 공개 접미사 목록을 내려받아 쓰지 않습니다.
    registry.add_recognizer(_KoreanPatternRecognizer("EMAIL_ADDRESS", [
        Pattern("email", r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])", 0.8),
    ], ["메일", "email"]))
    registry.add_recognizer(CreditCardRecognizer(supported_language=LANG))
    return AnalyzerEngine(registry=registry, nlp_engine=PatternOnlyNlpEngine(), supported_languages=[LANG],
                          context_aware_enhancer=WindowContextEnhancer())


@dataclass
class Redaction:
    text: str
    counts: Counter


class KoreanRedactor:
    def __init__(self) -> None:
        self.analyzer = build_analyzer()
        self.anonymizer = AnonymizerEngine()
        self.operators = {k: OperatorConfig("replace", {"new_value": v}) for k, v in LABELS.items()}

    def redact_text(self, text: str) -> Redaction:
        if not text:
            return Redaction(text, Counter())
        results: list[RecognizerResult] = self.analyzer.analyze(text=text, language=LANG,
                                                                score_threshold=THRESHOLD)
        if not results:
            return Redaction(text, Counter())
        out = self.anonymizer.anonymize(text=text, analyzer_results=results, operators=self.operators)
        return Redaction(out.text, Counter(i.entity_type for i in out.items))

    def __call__(self, body: dict[str, Any]) -> tuple[dict[str, Any], Counter]:
        """messages의 문자열 내용을 가린 새 본문과 개체 종류별 개수를 돌려줍니다."""
        total: Counter = Counter()
        messages = []
        for m in body.get("messages", []):
            m = dict(m)
            content = m.get("content")
            if isinstance(content, str):
                r = self.redact_text(content)
                m["content"], total = r.text, total + r.counts
            elif isinstance(content, list):
                parts = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                        r = self.redact_text(p["text"])
                        p, total = {**p, "text": r.text}, total + r.counts
                    parts.append(p)
                m["content"] = parts
            messages.append(m)
        return {**body, "messages": messages}, total
