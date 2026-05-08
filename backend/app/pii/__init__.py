"""PII masking pipeline — pass 1 (regex), pass 2 (Presidio), pass 3 (output guard)."""

from backend.app.pii.form_detector import flag_pii_items
from backend.app.pii.output_guard import scan
from backend.app.pii.presidio_masker import presidio_mask
from backend.app.pii.regex_masker import mask as regex_mask


def mask_all(text: str) -> str:
    """Full two-pass PII masker: regex (pass 1) → Presidio Korean NER (pass 2)."""
    return presidio_mask(regex_mask(text))


__all__ = ["mask_all", "regex_mask", "presidio_mask", "scan", "flag_pii_items"]
