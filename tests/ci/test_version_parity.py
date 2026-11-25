"""Unit test enforcing version parity across pyproject.toml, _version.py, README.md, CHANGELOG.md, and release.yml."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_version_parity_across_project_files() -> None:
    """Asserts that pyproject.toml, _version.py, README.md, CHANGELOG.md, and release.yml agree."""
    pyproject_data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version: str = pyproject_data["project"]["version"]

    version_py = (PROJECT_ROOT / "src" / "expedition33_rpc" / "_version.py").read_text(
        encoding="utf-8"
    )
    ver_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', version_py, re.MULTILINE)
    assert ver_match is not None, "Could not find __version__ in _version.py"
    code_version = ver_match.group(1)
    assert code_version == pyproject_version

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_match = re.search(r"release-v([0-9]+\.[0-9]+\.[0-9]+)", readme)
    assert readme_match is not None, "Could not find release-vX.Y.Z badge in README.md"
    assert readme_match.group(1) == pyproject_version

    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    changelog_match = re.search(r"^##\s+\[v?([0-9]+\.[0-9]+\.[0-9]+)\]", changelog, re.MULTILINE)
    assert changelog_match is not None, "Could not find ## [X.Y.Z] header in CHANGELOG.md"
    assert changelog_match.group(1) == pyproject_version

    release_yml = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "src/expedition33_rpc/_version.py" in release_yml
    assert "src/expedition33_rpc/__init__.py" not in release_yml
