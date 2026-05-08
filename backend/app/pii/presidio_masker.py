"""Pass-2 PII masker: Presidio with custom Korean recognizers.

Handles unstructured Korean PII that regex pass-1 cannot catch:
  [NAME]         — Korean personal names, gated by name-indicating keywords
  [ADDRESS]      — Korean administrative addresses (시/도 + 구/동/로)
  [AFFILIATION]  — Universities, research institutes, companies
  [STUDENT_ID]   — 8–10 digit student IDs gated by 학번 keyword

Uses custom PatternRecognizer instances with spaCy ko_core_news_sm as the
NLP backend. NAME and STUDENT_ID are handled by keyword-gated regex pre-passes;
ADDRESS and AFFILIATION go through the Presidio analyze→anonymize pipeline.
"""

import re

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# ── Korean name: keyword-gated approach ──────────────────────────────────────
# Only match Korean names when preceded by name-indicating keywords.
# This eliminates all false positives from common form labels (주소, 소속, 이메일…)
# that would otherwise match the surname-dictionary approach.
# The keyword prefix is captured in group 1 and restored; only group 2 is masked.

_NAME_KEYWORDS = re.compile(
    r"((?:이름|성명|신청자|책임자|연구책임자|공동연구자|연구자|저자|발표자|"
    r"발명자|출원자|특허권자|지원자|학생연구원|담당자|보조연구원)[:\s]*)"
    r"([가-힣]{2,4})"
)

# ── Korean administrative address prefixes ────────────────────────────────────

_CITY_PROVINCE = (
    r"서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|"
    r"경기도|강원도|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|제주특별자치도|"
    r"서울시|부산시|대구시|인천시|광주시|대전시|울산시"
)

# Address: city/province prefix followed by optional detail (구/동/로/길/번지/호 etc.)
_ADDRESS_DETAIL = r"(?:\s+[가-힣\w]+(?:구|시|군|동|읍|면|리|로|길|대로|번길)[\w\s\-]*){0,4}"
_ADDRESS_PATTERN = rf"(?:{_CITY_PROVINCE}){_ADDRESS_DETAIL}"

# ── Korean affiliation patterns ───────────────────────────────────────────────

# Endings that mark an organization name.
_AFFIL_SUFFIX = (
    r"대학교(?:병원)?|대학원|대학|연구소|연구원|병원|학원|"
    r"주식회사|유한회사|합자회사|협회|재단|공단|공사|기관"
)

# Pattern 1: word(s) ending with an affiliation suffix, at least 2 Hangul chars before.
_HANGUL_SYLLABLE = r"[가-힣]"
_AFFIL_WORD = rf"{_HANGUL_SYLLABLE}{{2,}}(?:{_AFFIL_SUFFIX})"

# Pattern 2: (주)... company shorthand
_AFFIL_PAREN = rf"(?:\(주\)|㈜){_HANGUL_SYLLABLE}{{1,10}}"

_AFFIL_PATTERN = rf"(?:{_AFFIL_PAREN}|{_AFFIL_WORD})"

# ── Student ID pattern ────────────────────────────────────────────────────────

# 학번 keyword + optional separator + 8–10 digits (hyphens allowed inside).
_STUDENT_ID_PATTERN = r"(?:학번\s*[:：]?\s*)(\d{4}[-]?\d{4,6})"

# ── Recognizer builders ───────────────────────────────────────────────────────


def _make_address_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="KR_ADDRESS",
        supported_language="ko",
        patterns=[Pattern(name="kr_address", regex=_ADDRESS_PATTERN, score=0.85)],
        context=["주소", "거주지", "근무지", "소재지", "위치"],
    )


def _make_affiliation_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="KR_AFFILIATION",
        supported_language="ko",
        patterns=[Pattern(name="kr_affiliation", regex=_AFFIL_PATTERN, score=0.8)],
        context=["소속", "기관", "근무", "재직", "출신", "학교", "대학"],
    )


# ── Engine construction ───────────────────────────────────────────────────────


def _build_engine() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    recognizers = [
        _make_address_recognizer(),
        _make_affiliation_recognizer(),
    ]
    # Pass recognizers and supported_languages together so the registry does
    # not default-load the English-only built-in recognizers.
    registry = RecognizerRegistry(
        recognizers=recognizers,
        supported_languages=["ko"],
    )

    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "ko", "model_name": "ko_core_news_sm"}],
        }
    ).create_engine()

    analyzer = AnalyzerEngine(
        registry=registry,
        nlp_engine=nlp_engine,
        supported_languages=["ko"],
    )
    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


_analyzer, _anonymizer = _build_engine()

_OPERATORS: dict[str, OperatorConfig] = {
    "KR_ADDRESS": OperatorConfig("replace", {"new_value": "[ADDRESS]"}),
    "KR_AFFILIATION": OperatorConfig("replace", {"new_value": "[AFFILIATION]"}),
    "DEFAULT": OperatorConfig("keep", {}),
}

# ── Public API ────────────────────────────────────────────────────────────────

# Pre-compiled pattern to find pass-1 placeholder tokens so they are
# shielded from Presidio before analysis and restored afterward.
_TOKEN_RE = re.compile(r"\[(JUMIN|CARD|ACCOUNT|PHONE|EMAIL|MONEY)\]")
_PLACEHOLDER_TMPL = "\x00TOKEN{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00TOKEN(\d+)\x00")


def presidio_mask(text: str) -> str:
    """Replace unstructured Korean PII with typed tokens (pass 2).

    Pass-1 placeholder tokens such as [JUMIN] are shielded so Presidio
    cannot accidentally fragment or duplicate them.
    """
    # Shield pass-1 tokens.
    shields: list[str] = []

    def _shield(m: re.Match) -> str:
        idx = len(shields)
        shields.append(m.group(0))
        return _PLACEHOLDER_TMPL.format(idx)

    shielded = _TOKEN_RE.sub(_shield, text)

    # Student ID: keyword-gated regex pre-pass.
    shielded = re.sub(_STUDENT_ID_PATTERN, "[STUDENT_ID]", shielded)

    # Name: keyword-gated regex pre-pass. Preserve the keyword prefix; mask only the name value.
    shielded = _NAME_KEYWORDS.sub(lambda m: m.group(1) + "[NAME]", shielded)

    # Analyze and anonymize the remaining text through Presidio (address + affiliation).
    entities = ["KR_ADDRESS", "KR_AFFILIATION"]
    results = _analyzer.analyze(text=shielded, language="ko", entities=entities)

    if results:
        anonymized = _anonymizer.anonymize(
            text=shielded,
            analyzer_results=results,
            operators=_OPERATORS,
        )
        output = anonymized.text
    else:
        output = shielded

    # Restore shielded pass-1 tokens.
    def _restore(m: re.Match) -> str:
        return shields[int(m.group(1))]

    return _PLACEHOLDER_RE.sub(_restore, output)
