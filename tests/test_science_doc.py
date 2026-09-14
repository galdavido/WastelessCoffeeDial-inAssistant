"""Every constant must cite a real section of docs/science.md, and vice versa.

This is what stops magic numbers accumulating in the engine. A constant whose
anchor doesn't resolve fails the build; a section nobody cites is either dead
prose or a constant someone forgot to register.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from core.brewing import CONSTANTS

_DOC = Path(__file__).resolve().parents[1] / "docs" / "science.md"
_ANCHOR_IN_HEADING = re.compile(r"^#{1,4} .*\{#([a-z0-9-]+)\}\s*$", re.MULTILINE)


def _doc_anchors() -> set[str]:
    return set(_ANCHOR_IN_HEADING.findall(_DOC.read_text(encoding="utf-8")))


class TestScienceDoc(unittest.TestCase):
    def test_doc_exists(self) -> None:
        self.assertTrue(_DOC.is_file(), f"missing {_DOC}")

    def test_every_constant_anchor_resolves(self) -> None:
        anchors = _doc_anchors()
        self.assertTrue(anchors, "no {#anchor} headings found in science.md")
        for name, constant in CONSTANTS.items():
            anchor = constant.anchor.lstrip("#")
            self.assertIn(
                anchor,
                anchors,
                f"constant {name!r} cites #{anchor}, which is not a heading "
                f"in docs/science.md",
            )

    def test_every_constant_declares_a_known_kind(self) -> None:
        allowed = {"PHYSICS", "LITERATURE", "CALIBRATED", "HEURISTIC"}
        for name, constant in CONSTANTS.items():
            self.assertIn(constant.kind, allowed, name)

    def test_heuristics_are_listed_under_the_heuristics_section(self) -> None:
        """A number we invented must be admitted as such in the doc."""
        text = _DOC.read_text(encoding="utf-8")
        start = text.index("{#heuristics}")
        end = text.index("{#method-levers}")
        heuristics_section = text[start:end]
        # Every heuristic constant's anchor must point inside that section.
        heuristic_anchors = {
            c.anchor.lstrip("#") for c in CONSTANTS.values() if c.kind == "HEURISTIC"
        }
        for anchor in heuristic_anchors:
            # #limits is shared with the scope section; the rest must be local.
            if anchor in ("limits", "method-levers"):
                continue
            self.assertIn(
                f"{{#{anchor}}}",
                heuristics_section,
                f"heuristic anchor #{anchor} is not declared under §5 Heuristics",
            )

    def test_no_orphan_anchors(self) -> None:
        """Sections exist to be cited. Narrative-only anchors are allowlisted."""
        narrative = {
            "limits",
            "physics",
            "literature",
            "calibrated",
            "heuristics",
            "method-levers",
            "simulator",
            "darcy",
            "normalised-time",
            "beta-law",
            # Derivations, not constants: they explain how a value is
            # computed rather than declaring one.
            "cold-start",
            "ey-formula",
            "sca-bands",
            "cameron",
            "taste-mapping",
            # Recorded decisions, not yet a constant: each explains a policy
            # conclusion and the shape a future threshold would take, without
            # fixing a number the engine uses today.
            "target-reachability",
            "deadband",
        }
        cited = {c.anchor.lstrip("#") for c in CONSTANTS.values()}
        orphans = _doc_anchors() - cited - narrative
        self.assertEqual(
            orphans, set(), f"science.md sections nothing cites: {sorted(orphans)}"
        )


if __name__ == "__main__":
    unittest.main()
