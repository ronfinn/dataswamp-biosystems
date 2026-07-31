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

Paths are compared after :meth:`~pathlib.Path.resolve`, so ``..`` segments,
redundant separators and symlink aliases cannot smuggle an unsafe path past the
check. Siblings are unaffected: with truth at ``generated/truth``, an estate at
``generated/estate`` shares no ancestor/descendant relationship with it and
remains valid. The rule protects the specific inputs a command needs, not every
path that happens to look related.
"""

from __future__ import annotations

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


def resolve_path(path: Path | str) -> Path:
    """Resolve ``path`` for comparison, expanding ``~`` and following symlinks.

    Non-destructive and safe for a path that does not exist yet: the existing
    prefix is resolved and the remainder normalised lexically.
    """
    return Path(path).expanduser().resolve()


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
