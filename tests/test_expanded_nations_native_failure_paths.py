from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations import (
    ExpandedNationsError,
    deactivate_actor_projection,
)
from gates_of_codex.expanded_nations_models import PORTRAIT_ROOT_RELATIVE


class ExpandedNationsNativeFailurePathTests(unittest.TestCase):
    def test_core_refuses_orphaned_generated_portrait_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            orphan = (
                root
                / PORTRAIT_ROOT_RELATIVE
                / "goc_serb_rifle(rusa)_00.png"
            )
            orphan.parent.mkdir(parents=True)
            orphan.write_bytes(b"\x89PNG\r\n\x1a\norphan")

            with self.assertRaisesRegex(
                ExpandedNationsError,
                "presentation files exist without an activation manifest",
            ):
                deactivate_actor_projection(root)

            self.assertTrue(orphan.is_file())


if __name__ == "__main__":
    unittest.main()
