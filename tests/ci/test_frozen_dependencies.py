"""CI test validating frozen dependencies in pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

EXPECTED_PROJECT_DEPENDENCIES = [
    "pystray>=0.19.5",
    "pillow>=10.0.0",
    "psutil>=5.9.0",
]

EXPECTED_DEV_DEPENDENCIES = [
    "pyinstaller>=6.0.0",
    "ruff>=0.9.0",
    "pyright>=1.1.0",
    "pytest>=8.0.0",
]


def test_frozen_dependencies() -> None:
    """Verifies that project.dependencies and dependency-groups.dev are strictly immutable."""
    root_dir = Path(__file__).resolve().parents[2]
    pyproject_path = root_dir / "pyproject.toml"

    assert pyproject_path.exists(), f"pyproject.toml missing at {pyproject_path}"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project_deps = data.get("project", {}).get("dependencies", [])
    dev_deps = data.get("dependency-groups", {}).get("dev", [])

    assert project_deps == EXPECTED_PROJECT_DEPENDENCIES, (
        f"project.dependencies mutated: expected {EXPECTED_PROJECT_DEPENDENCIES}, got {project_deps}"
    )

    assert dev_deps == EXPECTED_DEV_DEPENDENCIES, (
        f"dependency-groups.dev mutated: expected {EXPECTED_DEV_DEPENDENCIES}, got {dev_deps}"
    )
