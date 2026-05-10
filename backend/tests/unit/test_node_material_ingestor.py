"""Unit tests for MaterialIngestor node — TDD.

Key invariant (CLAUDE.md §Hard rules rule 1):
    extract → mask_all → summarize/Solar
    mask_all MUST be called before any Solar call.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.app.graph.state import GraphState, MaterialBundle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JUMIN_RAW = "901231-1234567"
_JUMIN_MASKED = "[JUMIN]"

_SAMPLE_TEXT = f"연구자 홍길동, 주민번호: {_JUMIN_RAW}, 연구 분야는 인공지능입니다."
_SAMPLE_BYTES = _SAMPLE_TEXT.encode("utf-8")
_SAMPLE_FILENAME = "cv.txt"
_SAMPLE_SUMMARY = "인공지능 분야 연구자의 이력 문서입니다."


def _state_with_materials(docs: list[dict] | None = None) -> GraphState:
    bundle = MaterialBundle(docs=docs or [])
    return GraphState(materials=bundle)


def _make_file_tuple(
    filename: str = _SAMPLE_FILENAME, content: bytes = _SAMPLE_BYTES
) -> tuple[str, bytes]:
    return (filename, content)


# ---------------------------------------------------------------------------
# Step 1: Pipeline order — mask_all called BEFORE summarize (spy test)
# ---------------------------------------------------------------------------


class TestPipelineOrder:
    def test_mask_all_called_before_summarize(self):
        """Spy confirms mask_all is invoked before the Solar summarize call."""
        call_order: list[str] = []

        def mock_extract(path):
            return _SAMPLE_TEXT

        def mock_mask_all(text: str) -> str:
            call_order.append("mask_all")
            return text.replace(_JUMIN_RAW, _JUMIN_MASKED)

        def mock_summarize(text: str, filename: str) -> str:
            call_order.append("summarize")
            return _SAMPLE_SUMMARY

        state = _state_with_materials()
        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=mock_mask_all),
            patch(
                "backend.app.graph.nodes.material_ingestor.summarize", side_effect=mock_summarize
            ),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            ingest_materials(state, [_make_file_tuple()])

        assert call_order == ["mask_all", "summarize"], (
            f"Expected mask_all before summarize, got: {call_order}"
        )

    def test_mask_all_called_before_summarize_multiple_files(self):
        """With multiple files, mask_all always precedes summarize for each file."""
        call_order: list[str] = []

        def mock_extract(path):
            return _SAMPLE_TEXT

        def mock_mask_all(text: str) -> str:
            call_order.append("mask_all")
            return text.replace(_JUMIN_RAW, _JUMIN_MASKED)

        def mock_summarize(text: str, filename: str) -> str:
            call_order.append("summarize")
            return _SAMPLE_SUMMARY

        state = _state_with_materials()
        files = [_make_file_tuple("a.txt"), _make_file_tuple("b.txt")]

        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=mock_mask_all),
            patch(
                "backend.app.graph.nodes.material_ingestor.summarize", side_effect=mock_summarize
            ),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            ingest_materials(state, files)

        assert call_order == ["mask_all", "summarize", "mask_all", "summarize"], (
            f"Expected alternating mask_all/summarize, got: {call_order}"
        )


# ---------------------------------------------------------------------------
# Step 3: PII invariant — Solar receives only masked text (no raw JUMIN)
# ---------------------------------------------------------------------------


class TestPiiInvariant:
    def test_solar_never_receives_raw_jumin(self):
        """Solar mock must NOT receive the raw 주민번호 string."""
        solar_received_texts: list[str] = []

        def mock_extract(path):
            return _SAMPLE_TEXT  # contains _JUMIN_RAW

        def mock_mask_all(text: str) -> str:
            return text.replace(_JUMIN_RAW, _JUMIN_MASKED)

        def mock_solar_complete(messages: list[dict]) -> str:
            for msg in messages:
                solar_received_texts.append(msg.get("content", ""))
            return _SAMPLE_SUMMARY

        state = _state_with_materials()
        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=mock_mask_all),
            patch(
                "backend.app.materials.summarize._solar_complete", side_effect=mock_solar_complete
            ),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            ingest_materials(state, [_make_file_tuple()])

        all_text = " ".join(solar_received_texts)
        assert _JUMIN_RAW not in all_text, (
            f"Raw 주민번호 leaked to Solar: found '{_JUMIN_RAW}' in Solar input"
        )

    def test_solar_receives_jumin_token_instead(self):
        """Solar input contains the masked token [JUMIN], not the raw number."""
        solar_received_texts: list[str] = []

        def mock_extract(path):
            return _SAMPLE_TEXT

        def mock_mask_all(text: str) -> str:
            return text.replace(_JUMIN_RAW, _JUMIN_MASKED)

        def mock_solar_complete(messages: list[dict]) -> str:
            for msg in messages:
                solar_received_texts.append(msg.get("content", ""))
            return _SAMPLE_SUMMARY

        state = _state_with_materials()
        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=mock_mask_all),
            patch(
                "backend.app.materials.summarize._solar_complete", side_effect=mock_solar_complete
            ),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            ingest_materials(state, [_make_file_tuple()])

        all_text = " ".join(solar_received_texts)
        assert _JUMIN_MASKED in all_text, "Expected [JUMIN] token in Solar input, but not found"

    def test_masked_text_stored_in_bundle_not_raw(self):
        """The MaterialBundle stores masked text, not the raw PII text."""

        def mock_extract(path):
            return _SAMPLE_TEXT

        def mock_mask_all(text: str) -> str:
            return text.replace(_JUMIN_RAW, _JUMIN_MASKED)

        state = _state_with_materials()
        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=mock_mask_all),
            patch(
                "backend.app.graph.nodes.material_ingestor.summarize", return_value=_SAMPLE_SUMMARY
            ),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])

        bundle: MaterialBundle = result["materials"]
        doc = bundle.docs[0]
        assert _JUMIN_RAW not in doc["masked_text"]
        assert _JUMIN_MASKED in doc["masked_text"]


# ---------------------------------------------------------------------------
# Existing materials preserved
# ---------------------------------------------------------------------------


class TestMaterialsPreservation:
    def test_existing_docs_preserved(self):
        """Adding new materials does not discard previously ingested docs."""
        existing_doc = {
            "filename": "old.txt",
            "summary": "기존 요약",
            "masked_text": "기존 내용",
            "raw_len": 5,
        }
        state = _state_with_materials(docs=[existing_doc])

        def mock_extract(path):
            return "새 내용입니다."

        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="새 요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple("new.txt", b"new content")])

        bundle: MaterialBundle = result["materials"]
        filenames = [d["filename"] for d in bundle.docs]
        assert "old.txt" in filenames
        assert "new.txt" in filenames

    def test_existing_docs_content_unchanged(self):
        """Existing doc data is not mutated."""
        existing_doc = {
            "filename": "old.txt",
            "summary": "기존 요약",
            "masked_text": "기존 내용",
            "raw_len": 5,
        }
        state = _state_with_materials(docs=[existing_doc])

        def mock_extract(path):
            return "새 내용"

        with (
            patch(
                "backend.app.graph.nodes.material_ingestor.extract_text", side_effect=mock_extract
            ),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="새 요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple("new.txt", b"new")])

        bundle: MaterialBundle = result["materials"]
        old = next(d for d in bundle.docs if d["filename"] == "old.txt")
        assert old["summary"] == "기존 요약"
        assert old["masked_text"] == "기존 내용"
        assert old["raw_len"] == 5


# ---------------------------------------------------------------------------
# Return structure — correct MaterialBundle fields
# ---------------------------------------------------------------------------


class TestReturnStructure:
    def test_returns_dict_with_materials_key(self):
        state = _state_with_materials()
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])
        assert "materials" in result

    def test_returns_material_bundle_instance(self):
        state = _state_with_materials()
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])
        assert isinstance(result["materials"], MaterialBundle)

    def test_doc_has_all_required_fields(self):
        state = _state_with_materials()
        raw_text = "내용입니다."
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value=raw_text),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])

        doc = result["materials"].docs[0]
        assert "filename" in doc
        assert "summary" in doc
        assert "masked_text" in doc
        assert "raw_len" in doc

    def test_doc_filename_matches_input(self):
        state = _state_with_materials()
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple("thesis.pdf", b"bytes")])

        assert result["materials"].docs[0]["filename"] == "thesis.pdf"

    def test_doc_raw_len_matches_extracted_text(self):
        state = _state_with_materials()
        raw_text = "12345"
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value=raw_text),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])

        assert result["materials"].docs[0]["raw_len"] == len(raw_text)

    def test_doc_summary_matches_summarize_output(self):
        state = _state_with_materials()
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch(
                "backend.app.graph.nodes.material_ingestor.summarize", return_value="테스트 요약"
            ),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])

        assert result["materials"].docs[0]["summary"] == "테스트 요약"


# ---------------------------------------------------------------------------
# Multiple files in one call
# ---------------------------------------------------------------------------


class TestMultipleFiles:
    def test_multiple_files_all_ingested(self):
        state = _state_with_materials()
        files = [
            _make_file_tuple("a.txt", b"a content"),
            _make_file_tuple("b.txt", b"b content"),
            _make_file_tuple("c.txt", b"c content"),
        ]

        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, files)

        assert len(result["materials"].docs) == 3

    def test_multiple_files_filenames_correct(self):
        state = _state_with_materials()
        files = [
            _make_file_tuple("first.txt", b"first"),
            _make_file_tuple("second.pdf", b"second"),
        ]

        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, files)

        filenames = [d["filename"] for d in result["materials"].docs]
        assert "first.txt" in filenames
        assert "second.pdf" in filenames


# ---------------------------------------------------------------------------
# Raw bytes input (in-memory file)
# ---------------------------------------------------------------------------


class TestRawBytesInput:
    def test_txt_bytes_ingested(self):
        """txt bytes are written to a temp file and then extracted correctly."""
        content = "이것은 인메모리 텍스트 파일입니다."
        state = _state_with_materials()

        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value=content),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [("memo.txt", content.encode("utf-8"))])

        doc = result["materials"].docs[0]
        assert doc["filename"] == "memo.txt"
        assert doc["masked_text"] == content
        assert doc["raw_len"] == len(content)

    def test_empty_state_starts_empty(self):
        """Starting from empty state with one file results in exactly 1 doc."""
        state = GraphState()
        with (
            patch("backend.app.graph.nodes.material_ingestor.extract_text", return_value="내용"),
            patch("backend.app.graph.nodes.material_ingestor.mask_all", side_effect=lambda t: t),
            patch("backend.app.graph.nodes.material_ingestor.summarize", return_value="요약"),
        ):
            from backend.app.graph.nodes.material_ingestor import ingest_materials

            result = ingest_materials(state, [_make_file_tuple()])

        assert len(result["materials"].docs) == 1
