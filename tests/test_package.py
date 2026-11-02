"""Harness smoke test: the package imports and exposes its version."""

import hockey_model


def test_package_exposes_version() -> None:
    assert hockey_model.__version__ == "0.1.0"
