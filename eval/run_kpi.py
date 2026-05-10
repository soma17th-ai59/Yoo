"""KPI measurement script — K1 to K6 (spec §8).

Run:
  uv run python eval/run_kpi.py            # always: K1, K5
  SOLAR_API_KEY=... uv run python eval/run_kpi.py --live   # adds K2, K3, K4, K6

Exits non-zero if K1 < 0.85 or K5 > 0 (KPI gates).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from backend.app.hwpx.parser import parse_hwpx
from backend.app.pii import output_guard
from backend.app.pii.form_detector import flag_pii_items

ROOT = Path(__file__).parent
FORMS_DIR = ROOT / "forms"
LABELS_PATH = ROOT / "form_labels.json"
TESTSET_PATH = ROOT / "router_testset.json"
MATERIALS_DIR = ROOT / "materials"

K1_TARGET = 0.85
K2_TARGET = 0.90
K3_TARGET = 0.60
K4_TARGET = 0.75
K6_TARGET_S = 30.0


# ---------------------------------------------------------------------------
# Pure helpers (testable without API)
# ---------------------------------------------------------------------------


def f1_score(predicted: list[bool], truth: list[bool]) -> dict[str, float]:
    """Precision / recall / F1 of binary predictions vs truth.

    No-positive corner case: if both lists have no True values, F1 = 1.0
    (perfect — there was nothing to find and nothing was wrongly flagged).
    """
    if len(predicted) != len(truth):
        raise ValueError("predicted and truth must align")
    tp = sum(1 for p, t in zip(predicted, truth) if p and t)
    fp = sum(1 for p, t in zip(predicted, truth) if p and not t)
    fn = sum(1 for p, t in zip(predicted, truth) if not p and t)
    if tp == 0 and fp == 0 and fn == 0:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def compute_k1(forms_dir: Path, labels_path: Path) -> dict[str, Any]:
    """K1: form-blank F1 (PII-flag detection) over all labeled forms."""
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    all_pred: list[bool] = []
    all_truth: list[bool] = []
    per_form: dict[str, dict[str, float]] = {}
    for entry in labels:
        fid = entry["file_id"]
        data = (forms_dir / f"{fid}.hwpx").read_bytes()
        doc = flag_pii_items(parse_hwpx(data))
        pred_map = {it.item_id: it.is_pii for it in doc.items}
        truth_map = {it["item_id"]: it["is_pii"] for it in entry["items"]}
        keys = sorted(pred_map.keys() & truth_map.keys())
        pred = [pred_map[k] for k in keys]
        truth = [truth_map[k] for k in keys]
        per_form[fid] = f1_score(pred, truth)
        all_pred.extend(pred)
        all_truth.extend(truth)
    return {"aggregate": f1_score(all_pred, all_truth), "per_form": per_form}


def scan_for_pii(text: str) -> list[str]:
    """K5 helper: list of leak reasons in the given text (empty list = clean)."""
    leaks: list[str] = []
    remaining = text
    # Re-run scan in a loop to surface multiple distinct leaks per text.
    seen = set()
    for _ in range(10):
        ok, reason = output_guard.scan(remaining)
        if ok:
            break
        if reason in seen:
            break
        seen.add(reason)
        leaks.append(reason)
        # Strip the matched pattern type from text on next pass.
        # Simplest: stop after one — prevents infinite loops.
        break
    return leaks


def compute_k5(materials_dir: Path) -> dict[str, Any]:
    """K5: PII leak count across all material text files. Must be 0."""
    leaks: list[dict[str, str]] = []
    for path in sorted(materials_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        ok, reason = output_guard.scan(text)
        if not ok:
            leaks.append({"path": str(path.relative_to(materials_dir)), "reason": reason})
    return {"leak_count": len(leaks), "leaks": leaks}


def compute_router_accuracy(predictions: list[str], testset: list[dict]) -> float:
    """K2 helper: predicted intents vs ground-truth intents."""
    if len(predictions) != len(testset):
        raise ValueError("predictions and testset must align")
    if not testset:
        return 0.0
    correct = sum(1 for p, t in zip(predictions, testset) if p == t["intent"])
    return correct / len(testset)


# ---------------------------------------------------------------------------
# Live measurements (require SOLAR_API_KEY)
# ---------------------------------------------------------------------------


def run_router_live(testset: list[dict]) -> list[str]:
    """K2 measurement is no longer meaningful — Router was removed.

    See docs/superpowers/specs/2026-05-08-per-item-actions-design.md Open Issue #1.
    """
    raise NotImplementedError("K2 (Router accuracy) is no longer measured — Router was removed.")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _row(label: str, value: str, target: str, passed: bool | None) -> str:
    flag = "PASS" if passed else ("FAIL" if passed is False else "SKIP")
    return f"  {label:<22} {value:<14} target={target:<10} [{flag}]"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="run live KPIs (K2-K6) using Solar API")
    args = parser.parse_args(argv)

    print("=" * 64)
    print("HwpAgent KPI Report")
    print("=" * 64)

    # K1 — always runs
    k1 = compute_k1(FORMS_DIR, LABELS_PATH)
    k1_f1 = k1["aggregate"]["f1"]
    k1_passed = k1_f1 >= K1_TARGET
    print(_row("K1 form-blank F1", f"{k1_f1:.3f}", f"≥ {K1_TARGET:.2f}", k1_passed))
    for fid, scores in k1["per_form"].items():
        print(
            f"      └─ {fid}: P={scores['precision']:.2f} R={scores['recall']:.2f} F1={scores['f1']:.2f}"
        )

    # K5 — always runs (over fixture materials)
    k5 = compute_k5(MATERIALS_DIR)
    k5_passed = k5["leak_count"] == 0
    print(_row("K5 PII leak count", str(k5["leak_count"]), "= 0", k5_passed))
    for leak in k5["leaks"]:
        print(f"      └─ {leak['path']}: {leak['reason']}")

    # K2 (Router accuracy) is no longer measured — Router was removed in
    # the per-item-actions refactor. See design doc Open Issue #1.
    print(_row("K2 router accuracy", "n/a (Router 제거)", f"≥ {K2_TARGET:.2f}", None))

    # K3, K4, K6 — live runs (need API)
    api_key = os.getenv("SOLAR_API_KEY")
    if args.live and api_key:
        # K3, K4, K6 require full graph runs which the harness would orchestrate.
        # Stub: not implemented in the V1 harness; leave SKIP for now.
        print(_row("K3 auto-fill rate", "—", f"≥ {K3_TARGET:.2f}", None))
        print(_row("K4 verifier first-pass", "—", f"≥ {K4_TARGET:.2f}", None))
        print(_row("K6 first-preview latency p50", "—", f"≤ {K6_TARGET_S:.0f}s", None))
    else:
        for label, target in [
            ("K3 auto-fill rate", f"≥ {K3_TARGET:.2f}"),
            ("K4 verifier first-pass", f"≥ {K4_TARGET:.2f}"),
            ("K6 first-preview latency", f"≤ {K6_TARGET_S:.0f}s"),
        ]:
            reason = "no SOLAR_API_KEY" if not api_key else "use --live"
            print(_row(label, f"skipped ({reason})", target, None))

    print("=" * 64)
    if not k1_passed:
        print("FAIL: K1 below target — non-zero exit.")
        return 1
    if not k5_passed:
        print("FAIL: K5 PII leak detected — non-zero exit.")
        return 1
    print("OK: K1 and K5 within target.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
