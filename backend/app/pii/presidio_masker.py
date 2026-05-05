"""Pass-2 PII masker: Presidio with custom Korean recognizers.

Handles unstructured Korean PII that regex pass-1 cannot catch:
  [NAME]         — Korean personal names (성 + 이름)
  [ADDRESS]      — Korean administrative addresses (시/도 + 구/동/로)
  [AFFILIATION]  — Universities, research institutes, companies
  [STUDENT_ID]   — 8–10 digit student IDs gated by 학번 keyword

Uses custom PatternRecognizer instances (no spaCy required) since
V1 spec explicitly permits simple regex + dictionary approach through
the Presidio API surface.
"""

import re

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# ── Korean surname dictionary (top 50+ by frequency) ─────────────────────────

_SURNAMES = (
    "김|이|박|최|정|강|조|윤|장|임|한|오|서|신|권|황|안|송|류|전|홍|고|문|양|손|배|백|허|유|남|"
    "심|노|하|곽|성|차|주|우|구|민|나|진|지|엄|채|원|천|방|공|현|함|변|염|여|추|도|소|석|선|설|"
    "마|길|국|표|명|기|반|라|왕|모|위"
)
# Note: 연 omitted — appears in 연구/연도/연락 compound words (false-positive risk).

_SURNAME_RE = f"(?:{_SURNAMES})"

# Korean given names: 1–3 Hangul syllables after a surname.
# Syllable range: AC00–D7A3 (가–힣)
_HANGUL_SYLLABLE = r"[가-힣]"
_GIVEN_RE = f"{_HANGUL_SYLLABLE}{{1,3}}"

# Full name pattern: surname + given name (≥2 syllables total), word-boundary anchored.
# Requiring 2+ total syllables means a 1-char surname needs a 1+ char given name.
# Negative lookahead on suffix prevents matching organization-ending words.
_NAME_PATTERN = rf"(?<!\w){_SURNAME_RE}{_GIVEN_RE}(?!\w)"

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
    r"대학교(?:병원)?|대학원|대학|연구소|연구원|연구원|병원|학원|"
    r"주식회사|유한회사|합자회사|협회|재단|공단|공사|기관"
)

# Pattern 1: word(s) ending with an affiliation suffix, at least 2 Hangul chars before.
_AFFIL_WORD = rf"{_HANGUL_SYLLABLE}{{2,}}(?:{_AFFIL_SUFFIX})"

# Pattern 2: (주)... company shorthand
_AFFIL_PAREN = rf"(?:\(주\)|㈜){_HANGUL_SYLLABLE}{{1,10}}"

_AFFIL_PATTERN = rf"(?:{_AFFIL_PAREN}|{_AFFIL_WORD})"

# ── Student ID pattern ────────────────────────────────────────────────────────

# 학번 keyword + optional separator + 8–10 digits (hyphens allowed inside).
_STUDENT_ID_PATTERN = r"(?:학번\s*[:：]?\s*)(\d{4}[-]?\d{4,6})"

# ── Recognizer builders ───────────────────────────────────────────────────────


def _make_name_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="KR_NAME",
        supported_language="ko",
        patterns=[Pattern(name="kr_name", regex=_NAME_PATTERN, score=0.7)],
        context=["이름", "성명", "연구책임자", "학생", "교수", "박사", "연구원", "담당자"],
    )


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


def _make_student_id_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="KR_STUDENT_ID",
        supported_language="ko",
        patterns=[Pattern(name="kr_student_id", regex=_STUDENT_ID_PATTERN, score=0.9)],
    )


# ── Engine construction ───────────────────────────────────────────────────────

def _build_engine() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    recognizers = [
        _make_name_recognizer(),
        _make_address_recognizer(),
        _make_affiliation_recognizer(),
        _make_student_id_recognizer(),
    ]
    # Pass recognizers and supported_languages together so the registry does
    # not default-load the English-only built-in recognizers.
    registry = RecognizerRegistry(
        recognizers=recognizers,
        supported_languages=["ko"],
    )

    nlp_engine = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "ko", "model_name": "ko_core_news_sm"}],
    }).create_engine()

    analyzer = AnalyzerEngine(
        registry=registry,
        nlp_engine=nlp_engine,
        supported_languages=["ko"],
    )
    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


_analyzer, _anonymizer = _build_engine()

_OPERATORS: dict[str, OperatorConfig] = {
    "KR_NAME": OperatorConfig("replace", {"new_value": "[NAME]"}),
    "KR_ADDRESS": OperatorConfig("replace", {"new_value": "[ADDRESS]"}),
    "KR_AFFILIATION": OperatorConfig("replace", {"new_value": "[AFFILIATION]"}),
    "KR_STUDENT_ID": OperatorConfig("replace", {"new_value": "[STUDENT_ID]"}),
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

    # Student ID: Presidio captures only the digit group, so we handle it
    # with a simple pre-pass to avoid keyword being left behind in output.
    def _mask_student_id(t: str) -> str:
        return re.sub(_STUDENT_ID_PATTERN, "[STUDENT_ID]", t)

    shielded = _mask_student_id(shielded)

    # Analyze and anonymize the remaining text through Presidio.
    # Exclude KR_STUDENT_ID from Presidio since we handled it above.
    entities = ["KR_NAME", "KR_ADDRESS", "KR_AFFILIATION"]
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
