"""Build eval fixtures deterministically.

Generates:
  eval/forms/{bk21,nrf_undergrad,conference_support}.hwpx
  eval/form_labels.json   — ground-truth items per form
  eval/materials/{학부생,석사1,석사2}/{cv,plan,report}.txt

Regenerate: `uv run python eval/build_eval.py`
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent
FORMS_DIR = ROOT / "forms"
MATERIALS_DIR = ROOT / "materials"
LABELS_PATH = ROOT / "form_labels.json"

MIMETYPE = b"application/hwp+zip"

CONTAINER_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="Contents/content.hpf" media-type="application/hwp+zip"/>
  </rootfiles>
</container>
"""

CONTENT_HPF = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentInformation
    xmlns:hpf="http://www.hancom.co.kr/hwpml/2011/hp">
  <hpf:manifest>
    <hpf:item id="Contents/section0.xml" mediaType="application/xml"/>
  </hpf:manifest>
</hpf:HWPFDocumentInformation>
"""


@dataclass
class FormSpec:
    file_id: str  # filename stem
    title: str  # human-readable
    paragraphs: list[tuple[str, bool]]  # (label, is_pii) — body paragraphs
    table_headers: list[str]  # 1 row of headers + 1 empty row
    pii_labels: frozenset[str]  # exact labels that are PII (parser strips prefixes via [:40])


def _section_xml(spec: FormSpec) -> bytes:
    para_blocks = "\n".join(
        f"  <hp:p><hp:run><hp:t>{label}</hp:t></hp:run></hp:p>"
        for label, _ in spec.paragraphs
    )
    header_cells = "\n      ".join(
        f"<hp:tc><hp:subList><hp:p><hp:run><hp:t>{h}</hp:t></hp:run></hp:p></hp:subList></hp:tc>"
        for h in spec.table_headers
    )
    empty_cells = "\n      ".join(
        "<hp:tc><hp:subList><hp:p><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList></hp:tc>"
        for _ in spec.table_headers
    )
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
{para_blocks}
  <hp:tbl>
    <hp:tr>
      {header_cells}
    </hp:tr>
    <hp:tr>
      {empty_cells}
    </hp:tr>
  </hp:tbl>
</hs:sec>
""".encode("utf-8")


def _write_hwpx(spec: FormSpec) -> Path:
    out = FORMS_DIR / f"{spec.file_id}.hwpx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, MIMETYPE)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("Contents/content.hpf", CONTENT_HPF)
        z.writestr("Contents/section0.xml", _section_xml(spec))
    out.write_bytes(buf.getvalue())
    return out


def _labels_from_parser(spec: FormSpec, hwpx_bytes: bytes) -> dict:
    """Derive labels by parsing the built .hwpx — guarantees label set matches parser."""
    from backend.app.hwpx.parser import parse_hwpx

    doc = parse_hwpx(hwpx_bytes)
    items = []
    for it in doc.items:
        items.append(
            {
                "item_id": it.item_id,
                "label": it.label,
                "section": it.section,
                "expected_chars": 200,
                "is_pii": it.label in spec.pii_labels,
            }
        )
    return {
        "file_id": spec.file_id,
        "title": spec.title,
        "items": items,
        "table_headers": spec.table_headers,
    }


# ---------------------------------------------------------------------------
# Form specs
# ---------------------------------------------------------------------------

FORMS: list[FormSpec] = [
    FormSpec(
        file_id="bk21",
        title="BK21 사업 신청서",
        paragraphs=[
            ("신청자 성명", True),
            ("소속 대학교", False),
            ("연구의 필요성", False),
            ("선행 연구 분석", False),
            ("연구 방법", False),
            ("예상 결과 및 활용 방안", False),
        ],
        table_headers=["분기", "추진 내용", "비고"],
        pii_labels=frozenset({"신청자 성명"}),
    ),
    FormSpec(
        file_id="nrf_undergrad",
        title="한국연구재단 학부생연구지원 신청서",
        paragraphs=[
            ("학번", True),
            ("이메일", True),
            ("연락처", True),
            ("연구 주제", False),
            ("연구 배경", False),
            ("연구 목표", False),
            ("연구 일정", False),
        ],
        table_headers=["항목", "금액", "사용 사유"],
        pii_labels=frozenset({"학번", "이메일", "연락처"}),
    ),
    FormSpec(
        file_id="conference_support",
        title="학회 발표 지원 신청서",
        paragraphs=[
            ("성명", True),
            ("주민등록번호", True),
            ("계좌번호", True),
            ("발표 논문 제목", False),
            ("학회명", False),
            ("발표 일자", False),
            ("발표 초록", False),
        ],
        table_headers=["공동저자 성명", "소속", "역할"],
        pii_labels=frozenset({"성명", "주민등록번호", "계좌번호", "공동저자 성명"}),
    ),
]


# ---------------------------------------------------------------------------
# Mock materials (no real PII)
# ---------------------------------------------------------------------------

MATERIALS: dict[str, dict[str, str]] = {
    "학부생": {
        "cv.txt": (
            "[이력서 — 익명]\n"
            "전공: 컴퓨터공학\n"
            "학년: 학부 4학년\n"
            "관심 분야: 자연어처리, 한국어 LLM 응용\n"
            "프로젝트: 한국어 문법 교정 모듈, BERT 기반 감성 분석\n"
            "수상: 교내 캡스톤 디자인 우수상 (2025)\n"
        ),
        "plan.txt": (
            "[연구계획 요약]\n"
            "주제: 한국어 학술 글쓰기 지원을 위한 LLM 기반 문장 다듬기 도구\n"
            "필요성: 비전공 한국어 학술 텍스트의 문장 품질 평가 부재\n"
            "방법: Solar 모델 + 도메인 특화 prompt + RLHF 미세조정\n"
            "기대 효과: 학부생 보고서 품질 표준화\n"
        ),
        "report.txt": (
            "[연구노트]\n"
            "9월: 데이터 수집 완료 (8,000 문장)\n"
            "10월: baseline BLEU 22.3 → fine-tuned 28.7\n"
            "11월: 사용자 만족도 설문 평균 4.1/5.0\n"
        ),
    },
    "석사1": {
        "cv.txt": (
            "[이력서 — 익명]\n"
            "전공: 데이터사이언스\n"
            "학년: 석사 1학기\n"
            "관심 분야: 헬스케어 NLP, 임상 노트 요약\n"
            "발표 경력: 한국정보과학회 2025 동계 워크숍 포스터\n"
        ),
        "plan.txt": (
            "[연구계획 요약]\n"
            "주제: 한국어 임상 노트 자동 요약을 통한 의료진 업무 부담 완화\n"
            "필요성: 한국어 임상 텍스트는 영문 대비 NLP 자원이 부족\n"
            "방법: ClinicalBERT-Ko + 추출형/생성형 하이브리드 요약\n"
            "기대 효과: 평균 노트 검토 시간 30% 단축\n"
        ),
        "report.txt": (
            "[연구노트]\n"
            "선행 연구 분석 완료 (40편)\n"
            "협력 병원 IRB 신청 진행 중\n"
            "베이스라인 ROUGE-L 0.41 확인\n"
        ),
    },
    "석사2": {
        "cv.txt": (
            "[이력서 — 익명]\n"
            "전공: 인공지능\n"
            "학년: 석사 3학기\n"
            "관심 분야: 멀티모달 학습, 영상-텍스트 결합 추론\n"
            "논문: 국내 학술지 1편 게재, 국제 컨퍼런스 워크숍 1편 발표\n"
        ),
        "plan.txt": (
            "[연구계획 요약]\n"
            "주제: 영상-텍스트 결합 모델의 한국어 OOD 견고성 분석\n"
            "필요성: 다국어 멀티모달 모델의 한국어 약점 정량화 부재\n"
            "방법: 한국어 OOD 벤치마크 구성 + 모델별 평가\n"
            "기대 효과: 한국어 멀티모달 평가 표준 제안\n"
        ),
        "report.txt": (
            "[연구노트]\n"
            "한국어 OOD 벤치마크 1차 5,000 샘플 구성\n"
            "기존 모델 4종 평가 결과 평균 정확도 67.4%\n"
            "다음 단계: 도메인 적응 기법 비교\n"
        ),
    },
}


def main() -> None:
    FORMS_DIR.mkdir(parents=True, exist_ok=True)
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

    labels_out: list[dict] = []
    for spec in FORMS:
        path = _write_hwpx(spec)
        print(f"wrote {path} ({path.stat().st_size} bytes)")
        labels_out.append(_labels_from_parser(spec, path.read_bytes()))

    LABELS_PATH.write_text(
        json.dumps(labels_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {LABELS_PATH}")

    for student, files in MATERIALS.items():
        student_dir = MATERIALS_DIR / student
        student_dir.mkdir(parents=True, exist_ok=True)
        for name, body in files.items():
            (student_dir / name).write_text(body, encoding="utf-8")
        print(f"wrote materials for {student}")


if __name__ == "__main__":
    main()
