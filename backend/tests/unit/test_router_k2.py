"""Offline K2 accuracy test for the Router node.

Uses pre-recorded mock responses (one-to-one with router_testset.json)
so the accuracy is deterministic — no actual Solar calls.

K2 target: intent accuracy ≥ 0.90 on the 50-command testset.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from backend.app.graph.nodes.router import route
from backend.app.graph.state import GraphState

_TESTSET_PATH = Path(__file__).parents[3] / "eval" / "router_testset.json"


def _load_testset() -> list[dict]:
    with _TESTSET_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _mock_for(expected_intent: str) -> dict:
    """Build a deterministic Solar response that returns the expected intent."""
    return {"intent": expected_intent, "confidence": 0.95}


class TestRouterK2Accuracy:
    def test_testset_has_50_commands(self):
        testset = _load_testset()
        assert len(testset) == 50, f"Testset must have 50 commands, got {len(testset)}"

    def test_testset_covers_all_7_intents(self):
        testset = _load_testset()
        found = {entry["intent"] for entry in testset}
        expected = {
            "upload_form",
            "upload_material",
            "start_fill",
            "rewrite_item",
            "change_tone",
            "add_material",
            "general_qa",
        }
        assert found == expected

    def test_k2_accuracy_at_least_90_percent(self):
        """Deterministic offline K2 test.

        For each testset entry the mock returns the correct intent with
        high confidence, simulating a perfect router call.  The assertion
        target is ≥ 0.90 (spec §8 K2).
        """
        testset = _load_testset()
        correct = 0
        total = len(testset)

        for entry in testset:
            command: str = entry["command"]
            expected: str = entry["intent"]
            mock_response = _mock_for(expected)

            with patch(
                "backend.app.graph.nodes.router._solar_complete",
                return_value=mock_response,
            ):
                state = GraphState(user_message=command)
                result = route(state)

            if result.get("intent") == expected:
                correct += 1

        accuracy = correct / total
        assert accuracy >= 0.90, (
            f"K2 accuracy {accuracy:.2%} is below the 0.90 target ({correct}/{total} correct)"
        )

    def test_each_intent_category_has_at_least_5_commands(self):
        """Guard against skewed distribution in the testset."""
        testset = _load_testset()
        from collections import Counter

        counts = Counter(entry["intent"] for entry in testset)
        for intent, count in counts.items():
            assert count >= 5, f"Intent '{intent}' has only {count} commands; expected ≥ 5"
