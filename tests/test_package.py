"""Smoke tests for the dataswamp_biosystems package."""

import dataswamp_biosystems


def test_package_imports() -> None:
    assert dataswamp_biosystems is not None


def test_version_is_defined_string() -> None:
    assert isinstance(dataswamp_biosystems.__version__, str)
    assert dataswamp_biosystems.__version__ == "0.1.0"
