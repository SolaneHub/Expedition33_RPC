"""CI test validating the architecture SVG diagrams integrity and size bounds."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = pytest.mark.ci

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
PIPELINE_SVG = DOCS_DIR / "architecture_pipeline.svg"
THREADING_SVG = DOCS_DIR / "architecture_threading.svg"
STATE_MACHINE_SVG = DOCS_DIR / "architecture_state_machine.svg"


@pytest.mark.parametrize(
    "svg_path,expected_tag",
    [
        (PIPELINE_SVG, "TELEMETRY &amp; PRESENCE PIPELINE"),
        (THREADING_SVG, "THREADING &amp; PLATFORM ABSTRACTION"),
        (STATE_MACHINE_SVG, "STATE MACHINE &amp; INVARIANT GUARANTEES"),
    ],
)
def test_architecture_svg_validity_and_compactness(svg_path: Path, expected_tag: str) -> None:
    """Verifies that architecture SVGs exist, are well-formed XML, compact (<15KB) and valid."""
    assert svg_path.exists(), f"SVG diagram missing: {svg_path}"

    size_bytes = os.path.getsize(svg_path)
    # GosuDRM style: lean, compact, vector-sharp (< 15 KB)
    assert 2000 < size_bytes < 15000, f"SVG diagram {svg_path.name} unexpected size: {size_bytes}B"

    content = svg_path.read_text(encoding="utf-8")
    assert expected_tag in content
    assert "@keyframes e33flow" in content
    assert "ui-sans-serif" in content

    # XML well-formedness verification
    tree = ET.parse(svg_path)
    root = tree.getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib.get("viewBox") == "0 0 880 470"
