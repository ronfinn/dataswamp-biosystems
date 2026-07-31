"""Shared output-directory safety policy for commands that replace directories.

Every generator writes by *replacing a whole directory*: output is staged in a
temporary sibling and swapped into place with :func:`os.replace`, after which the
previous contents are removed. That is safe for a directory the user owns as
generated output, and catastrophic for a directory holding required inputs — a
mistyped ``--output-dir config --force`` would replace the tracked, canonical,
non-regenerable configuration with generated output.

This module holds the single implementation of the rule that prevents it. It is
deliberately dependency-free (no Typer, no company/truth/estate/observed
imports) so every layer can apply the same policy, and so the CLI stays the only
place that translates a failure into an exit code.

Three overlaps are rejected, for each protected path:

``is``
    The output *is* the protected path — replacing it destroys it outright.
``contains``
    The output is an *ancestor* of the protected path, so replacing the output
    directory takes the protected path down with it. This is what rejects the
    repository root, ``.`` and ``..``: they all contain ``config/``. No explicit
    repository-root detection is needed, and none is attempted.
``is inside``
    The output is a *descendant* of a protected input, so generating into it
    would write inside a directory that must stay intact.

Paths are compared after :func:`resolve_path`, so ``..`` segments, redundant
separators, symlink aliases and — on a case-insensitive filesystem — differently
cased spellings of the same directory all reduce to one form before comparison.
Siblings are unaffected: with truth at ``generated/truth``, an estate at
``generated/estate`` shares no ancestor/descendant relationship with it and
remains valid. The rule protects the specific inputs a command needs, not every
path that happens to look related.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

# How the proposed output overlaps a protected path, rendered into the message.
_RELATION_PHRASES = {
    "is": "is",
    "contains": "contains",
    "is-inside": "is inside",
}

# Shared labels for the protected inputs, so every command words them the same.
CONFIG_INPUT_LABEL = "canonical configuration directory"
TRUTH_INPUT_LABEL = "truth input directory"


class PathSafetyError(Exception):
    """Base class for output-path safety failures."""


class UnsafeOutputDirectoryError(PathSafetyError):
    """A proposed output directory overlaps a protected input or structural path.

    Carries the resolved output, the offending protected path and its label, and
    the relationship between them, so a caller can render or re-wrap the failure
    without re-deriving any of it.
    """

    def __init__(
        self,
        output_dir: Path,
        protected_label: str,
        protected_path: Path,
        relation: str,
    ) -> None:
        self.output_dir = output_dir
        self.protected_label = protected_label
        self.protected_path = protected_path
        self.relation = relation
        phrase = _RELATION_PHRASES.get(relation, relation)
        super().__init__(
            f"unsafe output directory {output_dir}: it {phrase} the {protected_label} "
            f"({protected_path}). Generation replaces the entire output directory, so this "
            f"would destroy a protected input."
        )


def _canonical_component(parent: Path, part: str) -> str:
    """Return ``part`` as it is actually spelled inside ``parent``.

    :meth:`~pathlib.Path.resolve` follows symlinks but preserves whatever case
    the caller typed, so on a case-insensitive filesystem ``CONFIG`` and
    ``config`` name one directory yet compare unequal — which would let a case
    variant slip past the containment check. Consulting the directory *listing*
    (never :meth:`~pathlib.Path.exists`, which answers ``True`` for the wrong
    case on such a filesystem) recovers the real spelling.

    The lookup is filesystem-agnostic rather than platform-gated:

    * an exact entry always wins, so a case-sensitive filesystem is unaffected;
    * exactly one case-insensitive match is canonicalised to that entry;
    * several matches (possible only where case is significant) are genuinely
      distinct directories, so the requested spelling is kept rather than
      collapsing them onto an arbitrary one;
    * an unreadable or non-directory parent falls back to the requested
      spelling, leaving the comparison no weaker than a plain ``resolve``.
    """
    try:
        entries = sorted(entry.name for entry in os.scandir(parent))
    except OSError:
        return part
    if part in entries:
        return part
    folded = part.casefold()
    matches = [entry for entry in entries if entry.casefold() == folded]
    return matches[0] if len(matches) == 1 else part


def resolve_path(path: Path | str) -> Path:
    """Resolve ``path`` to the single canonical form used for every comparison.

    Expands ``~``, resolves symlinks and ``..`` via
    :meth:`~pathlib.Path.resolve`, then rewrites each component that exists on
    disk to its real spelling (see :func:`_canonical_component`), so equivalent
    paths compare equal and genuinely distinct ones stay distinct.

    Non-destructive and safe for a path that does not exist yet: components past
    the existing prefix are kept verbatim.
    """
    resolved = Path(path).expanduser().resolve()
    current = Path(resolved.anchor)
    for part in resolved.relative_to(resolved.anchor).parts:
        current = current / (_canonical_component(current, part) if current.is_dir() else part)
    return current


def ensure_safe_output_dir(
    output_dir: Path | str,
    *,
    protected_paths: Mapping[str, Path],
) -> Path:
    """Return the resolved ``output_dir``, or raise if it overlaps a protected path.

    ``protected_paths`` maps a human-readable label (used in the error message,
    e.g. ``"canonical configuration directory"``) to the path to protect. Labels
    are checked in sorted order so the reported conflict is deterministic when a
    path overlaps more than one protected location.

    Raises :class:`UnsafeOutputDirectoryError` before any filesystem mutation
    occurs. Callers must invoke this *before* staging, backing up, replacing or
    removing anything.
    """
    resolved = resolve_path(output_dir)
    for label in sorted(protected_paths):
        protected = resolve_path(protected_paths[label])
        if resolved == protected:
            raise UnsafeOutputDirectoryError(resolved, label, protected, "is")
        if protected.is_relative_to(resolved):
            raise UnsafeOutputDirectoryError(resolved, label, protected, "contains")
        if resolved.is_relative_to(protected):
            raise UnsafeOutputDirectoryError(resolved, label, protected, "is-inside")
    return resolved


__all__ = [
    "CONFIG_INPUT_LABEL",
    "TRUTH_INPUT_LABEL",
    "PathSafetyError",
    "UnsafeOutputDirectoryError",
    "resolve_path",
    "ensure_safe_output_dir",
]
