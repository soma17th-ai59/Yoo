"""Render the compiled HwpAgent LangGraph as Mermaid + PNG.

Outputs:
  docs/graph.mmd   — Mermaid source (offline)
  docs/graph.png   — Rendered diagram (uses mermaid.ink, requires network)

Usage:
  uv run python tools/draw_graph.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.app.graph.graph import build_compiled_graph

OUT_DIR = Path(__file__).parent.parent / "docs"


class _StubSession:
    """Minimal SessionProvider — drawing doesn't execute nodes."""

    def get_form_bytes(self, _sid: str) -> bytes:
        return b""

    def get_material_files(self, _sid: str) -> list[tuple[str, bytes]]:
        return []

    def put_rendered_bytes(self, _sid: str, _data: bytes) -> None:
        pass


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    graph = build_compiled_graph(_StubSession()).get_graph()

    mermaid_src = graph.draw_mermaid()
    mermaid_path = OUT_DIR / "graph.mmd"
    mermaid_path.write_text(mermaid_src, encoding="utf-8")
    print(f"wrote {mermaid_path} ({len(mermaid_src)} bytes)")

    png_path = OUT_DIR / "graph.png"
    try:
        png_bytes = graph.draw_mermaid_png()
        png_path.write_bytes(png_bytes)
        print(f"wrote {png_path} ({len(png_bytes)} bytes)")
    except Exception as exc:
        print(f"PNG render skipped — {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Mermaid source still saved; render at https://mermaid.live", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
