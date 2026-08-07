"""The project's licence split, and the one canonical copy of the data licence.

Two licences apply to two different things, and conflating them is the mistake
this module exists to prevent:

*The software* — everything in ``src/`` — is MIT. Commercial use included, no
permission needed.

*The official generated benchmark datasets and bundles the project distributes*,
from release v0.1.0 onward, are CC BY-NC 4.0. Noncommercial research, education
and AI/model/agent evaluation are permitted with attribution; commercial use
requires separate permission from the project owner.

That second licence is a statement about *what the project publishes*, not a
claim over data a third party independently generates by running the MIT
software themselves.

``DATA-LICENSE.md`` at the repository root is the single authoritative wording.
Bundles ship a byte-identical copy of that file rather than a paraphrase, so
there is exactly one text to keep correct, and a consumer who receives only a
bundle can read the terms without repository access. Resolution mirrors
:mod:`dataswamp_biosystems.examples`: a source checkout wins, the copy
force-included into the wheel is the fallback, and an editable install resolves
back to the checkout it imports from.
"""

from __future__ import annotations

from pathlib import Path

SOFTWARE_LICENSE = "MIT"

GENERATED_DATA_LICENSE = "CC-BY-NC-4.0"
GENERATED_DATA_LICENSE_NAME = "Creative Commons Attribution-NonCommercial 4.0 International"
GENERATED_DATA_LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"

# The release from which the generated-data licence applies. Prospective by
# design: nothing distributed earlier is retroactively relicensed.
GENERATED_DATA_LICENSE_SINCE = "v0.1.0"

DATA_LICENSE_NAME = "DATA-LICENSE.md"
COMMERCIAL_LICENSING_NAME = "COMMERCIAL-LICENSING.md"

CHECKOUT_DATA_LICENSE = Path(DATA_LICENSE_NAME)
PACKAGED_DATA_LICENSE = Path(__file__).resolve().parent / "_licenses" / DATA_LICENSE_NAME
SOURCE_DATA_LICENSE = Path(__file__).resolve().parents[2] / DATA_LICENSE_NAME


def data_license_path() -> Path:
    """Return the path to the canonical ``DATA-LICENSE.md``.

    Prefers a source checkout's copy so an edited licence is what ships, and
    falls back to the packaged copy for an installed-only user.
    """
    for candidate in (CHECKOUT_DATA_LICENSE, PACKAGED_DATA_LICENSE, SOURCE_DATA_LICENSE):
        if candidate.is_file():
            return candidate
    return PACKAGED_DATA_LICENSE


def data_license_text() -> str:
    """Return the canonical generated-data licence text.

    Raises :class:`OSError` if no copy can be found: a bundle that silently
    omitted its licence would be worse than a build that failed loudly.
    """
    return data_license_path().read_text(encoding="utf-8")


__all__ = [
    "SOFTWARE_LICENSE",
    "GENERATED_DATA_LICENSE",
    "GENERATED_DATA_LICENSE_NAME",
    "GENERATED_DATA_LICENSE_URL",
    "GENERATED_DATA_LICENSE_SINCE",
    "DATA_LICENSE_NAME",
    "COMMERCIAL_LICENSING_NAME",
    "CHECKOUT_DATA_LICENSE",
    "PACKAGED_DATA_LICENSE",
    "SOURCE_DATA_LICENSE",
    "data_license_path",
    "data_license_text",
]
