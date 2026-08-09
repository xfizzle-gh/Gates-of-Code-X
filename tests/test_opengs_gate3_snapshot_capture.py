from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "opengs_eval" / "gate3_prototype.py"


def load_module():
    spec = importlib.util.spec_from_file_location("gate3_prototype_capture_tests", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gate3StableCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load_module()

    @staticmethod
    def _stable_tree(root: Path) -> None:
        (root / "nested").mkdir()
        (root / "alpha.bin").write_bytes(b"alpha\x00authority")
        (root / "nested" / "beta.bin").write_bytes(b"beta\xffauthority")

    def test_stable_tree_captures_as_detached_immutable_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._stable_tree(root)
            snapshot = self.g.capture_tree(root)
            self.assertEqual(
                {"alpha.bin", "nested/beta.bin"}, set(snapshot.files)
            )
            self.assertEqual(frozenset({"nested"}), snapshot.directories)
            self.assertEqual(b"alpha\x00authority", snapshot.files["alpha.bin"])
            with self.assertRaises(TypeError):
                snapshot.files["other.bin"] = b"forbidden"

    def test_metadata_only_changes_do_not_replace_byte_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._stable_tree(root)

            def touch_metadata(captured_root: Path) -> None:
                os.utime(captured_root / "alpha.bin", None)
                os.utime(captured_root / "nested", None)
                os.utime(captured_root, None)

            snapshot = self.g.capture_tree_with_hook(root, touch_metadata)
            self.assertEqual(b"alpha\x00authority", snapshot.files["alpha.bin"])

    def test_real_byte_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._stable_tree(root)

            def mutate(captured_root: Path) -> None:
                (captured_root / "alpha.bin").write_bytes(b"changed-same-purpose")

            with self.assertRaisesRegex(
                self.g.Gate3Error, "file bytes changed during capture: alpha.bin"
            ):
                self.g.capture_tree_with_hook(root, mutate)

    def test_added_and_removed_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._stable_tree(root)

            def add(captured_root: Path) -> None:
                (captured_root / "added.bin").write_bytes(b"not-authorized")

            with self.assertRaisesRegex(
                self.g.Gate3Error, "file membership changed during capture"
            ):
                self.g.capture_tree_with_hook(root, add)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._stable_tree(root)

            def remove(captured_root: Path) -> None:
                (captured_root / "alpha.bin").unlink()

            with self.assertRaisesRegex(
                self.g.Gate3Error, "file membership changed during capture"
            ):
                self.g.capture_tree_with_hook(root, remove)

    def test_added_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._stable_tree(root)

            def add_directory(captured_root: Path) -> None:
                (captured_root / "late-directory").mkdir()

            with self.assertRaisesRegex(
                self.g.Gate3Error, "directory membership changed during capture"
            ):
                self.g.capture_tree_with_hook(root, add_directory)

    def test_symlink_and_nonregular_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.bin"
            target.write_bytes(b"target")
            link = root / "link.bin"
            try:
                link.symlink_to(target)
            except OSError:
                pass
            else:
                with self.assertRaisesRegex(self.g.Gate3Error, "symlink"):
                    self.g.capture_tree(root)

        if not hasattr(os, "mkfifo"):
            return
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fifo = root / "authority.pipe"
            try:
                os.mkfifo(fifo)
            except OSError:
                return
            with self.assertRaisesRegex(self.g.Gate3Error, "nonregular"):
                self.g.capture_tree(root)

    def test_mutation_after_capture_cannot_enter_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "source"
            output = Path(td) / "published"
            root.mkdir()
            self._stable_tree(root)
            snapshot = self.g.capture_tree(root)
            (root / "alpha.bin").write_bytes(b"post-capture-mutation")
            (root / "nested" / "injected.bin").write_bytes(b"injected")

            self.g.publish_snapshot(snapshot, output)

            self.assertEqual(
                b"alpha\x00authority", (output / "alpha.bin").read_bytes()
            )
            self.assertFalse((output / "nested" / "injected.bin").exists())
            self.assertEqual(
                dict(snapshot.files), dict(self.g.capture_tree(output).files)
            )

    def test_capture_is_independent_of_creation_and_iteration_order(self):
        with tempfile.TemporaryDirectory() as left_td, tempfile.TemporaryDirectory() as right_td:
            left = Path(left_td)
            right = Path(right_td)
            (left / "nested").mkdir()
            (left / "z.bin").write_bytes(b"z")
            (left / "nested" / "a.bin").write_bytes(b"a")

            (right / "nested").mkdir()
            (right / "nested" / "a.bin").write_bytes(b"a")
            (right / "z.bin").write_bytes(b"z")

            left_snapshot = self.g.capture_tree(left)
            right_snapshot = self.g.capture_tree(right)
            self.assertEqual(dict(left_snapshot.files), dict(right_snapshot.files))
            self.assertEqual(left_snapshot.directories, right_snapshot.directories)
            self.assertEqual(dict(left_snapshot.sha256), dict(right_snapshot.sha256))


if __name__ == "__main__":
    unittest.main()
