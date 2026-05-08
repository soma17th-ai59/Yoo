"""Unit tests for the KPI harness functions in eval/run_kpi.py.

Tests verify the harness logic — they do not measure KPIs against real targets.
"""

from __future__ import annotations

from pathlib import Path

from eval.run_kpi import (
    compute_k1,
    compute_k5,
    compute_router_accuracy,
    f1_score,
    main,
)

ROOT = Path(__file__).parent
FORMS_DIR = ROOT / "forms"
LABELS_PATH = ROOT / "form_labels.json"
MATERIALS_DIR = ROOT / "materials"


# ---------------------------------------------------------------------------
# f1_score
# ---------------------------------------------------------------------------


def test_f1_perfect_match():
    out = f1_score([True, False, True], [True, False, True])
    assert out == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_f1_all_negatives_is_perfect():
    out = f1_score([False, False], [False, False])
    assert out["f1"] == 1.0


def test_f1_with_misses():
    # 1 TP, 1 FP, 1 FN
    out = f1_score([True, True, False], [True, False, True])
    assert abs(out["precision"] - 0.5) < 1e-9
    assert abs(out["recall"] - 0.5) < 1e-9
    assert abs(out["f1"] - 0.5) < 1e-9


def test_f1_length_mismatch_raises():
    import pytest

    with pytest.raises(ValueError):
        f1_score([True], [True, False])


# ---------------------------------------------------------------------------
# compute_k1 against built fixtures
# ---------------------------------------------------------------------------


def test_k1_on_fixture_forms_meets_target():
    k1 = compute_k1(FORMS_DIR, LABELS_PATH)
    assert k1["aggregate"]["f1"] >= 0.85
    assert set(k1["per_form"].keys()) == {"bk21", "nrf_undergrad", "conference_support"}


# ---------------------------------------------------------------------------
# compute_k5
# ---------------------------------------------------------------------------


def test_k5_on_fixture_materials_is_zero():
    k5 = compute_k5(MATERIALS_DIR)
    assert k5["leak_count"] == 0
    assert k5["leaks"] == []


def test_k5_detects_jumin(tmp_path):
    (tmp_path / "leak.txt").write_text("주민 900101-1234567 입니다.", encoding="utf-8")
    k5 = compute_k5(tmp_path)
    assert k5["leak_count"] == 1
    assert "jumin" in k5["leaks"][0]["reason"]


def test_k5_skips_non_text_files(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")
    k5 = compute_k5(tmp_path)
    assert k5["leak_count"] == 0


# ---------------------------------------------------------------------------
# compute_router_accuracy
# ---------------------------------------------------------------------------


def test_router_accuracy_perfect():
    testset = [{"command": "x", "intent": "start_fill"}, {"command": "y", "intent": "general_qa"}]
    preds = ["start_fill", "general_qa"]
    assert compute_router_accuracy(preds, testset) == 1.0


def test_router_accuracy_partial():
    testset = [
        {"command": "a", "intent": "start_fill"},
        {"command": "b", "intent": "rewrite_item"},
        {"command": "c", "intent": "general_qa"},
        {"command": "d", "intent": "upload_form"},
    ]
    preds = ["start_fill", "rewrite_item", "upload_form", "upload_form"]
    assert compute_router_accuracy(preds, testset) == 0.75


def test_router_accuracy_length_mismatch_raises():
    import pytest

    with pytest.raises(ValueError):
        compute_router_accuracy(["start_fill"], [])


# ---------------------------------------------------------------------------
# main() — integration
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_clean_fixtures(monkeypatch, capsys):
    monkeypatch.delenv("SOLAR_API_KEY", raising=False)
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "K1 form-blank F1" in out
    assert "K5 PII leak count" in out
    assert "OK" in out
