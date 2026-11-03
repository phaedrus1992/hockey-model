"""Harness smoke test: the package imports and exposes its version."""

import hockey_model


def test_package_exposes_version() -> None:
    assert hockey_model.__version__ == "0.1.0"


def test_public_names_are_exported() -> None:
    expected = {
        "Player",
        "Roster",
        "Projection",
        "Catalog",
        "project_player",
        "project_team",
        "matchup",
        "playoff_probability",
        "nhl_roster",
    }
    assert expected <= set(hockey_model.__all__)
