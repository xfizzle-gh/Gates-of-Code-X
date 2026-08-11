from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "spikes" / "201-custom-tactical-factions"
DEPLOY = SPIKE / "deploy.ps1"
BACKUP = SPIKE / ".deploy-backup"

PARENT_CONQUEST = (
    "settings.set",
    "inf_ukr.set",
    "inf_rusa.set",
    "inf_nato.set",
    "inf_prc_era1960.set",
    "inf_csa_era1960.set",
    "units_ukr.set",
    "units_rusa.set",
    "units_nato.set",
    "units_sov_era1960.set",
    "units_csa_era1960.set",
    "units_prc_era1960.set",
)


def _find_powershell() -> str | None:
    candidates = ("pwsh", "powershell") if os.name != "nt" else ("powershell", "pwsh")
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_ps(args: list[str]) -> subprocess.CompletedProcess[str]:
    executable = _find_powershell()
    if not executable:
        raise unittest.SkipTest("PowerShell executable not available")
    return subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DEPLOY),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _make_workshop(root: Path) -> Path:
    workshop = root / "workshop"
    codex = workshop / "3261086933"
    conquest = codex / "resource" / "set" / "multiplayer" / "units" / "conquest"
    armies = codex / "resource" / "set" / "multiplayer" / "armies"
    conquest.mkdir(parents=True)
    armies.mkdir(parents=True)
    for name in PARENT_CONQUEST:
        _write(conquest / name, f"; parent body {name}\n")
    return workshop


class DeployRestoreHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        if BACKUP.exists():
            shutil.rmtree(BACKUP)

    def tearDown(self) -> None:
        if BACKUP.exists():
            shutil.rmtree(BACKUP)

    def test_restore_refuses_different_gates_root(self) -> None:
        if _find_powershell() is None:
            self.skipTest("PowerShell executable not available")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = _make_workshop(root)
            gates_a = root / "gates-a"
            gates_b = root / "gates-b"
            gates_b.mkdir(parents=True)

            deployed = _run_ps(
                ["-GatesRoot", str(gates_a), "-WorkshopRoot", str(workshop)]
            )
            self.assertEqual(deployed.returncode, 0, deployed.stdout + deployed.stderr)

            installed = (
                gates_a
                / "resource"
                / "set"
                / "multiplayer"
                / "armies"
                / "goc_dprk.set"
            )
            self.assertTrue(installed.is_file())

            wrong_restore = _run_ps(["-GatesRoot", str(gates_b), "-Restore"])
            self.assertNotEqual(
                wrong_restore.returncode,
                0,
                wrong_restore.stdout + wrong_restore.stderr,
            )
            self.assertIn(
                "different GatesRoot",
                wrong_restore.stdout + wrong_restore.stderr,
            )
            self.assertTrue(installed.is_file(), "wrong-root restore mutated the real target")

            correct_restore = _run_ps(["-GatesRoot", str(gates_a), "-Restore"])
            self.assertEqual(
                correct_restore.returncode,
                0,
                correct_restore.stdout + correct_restore.stderr,
            )
            self.assertFalse(installed.exists())

    def test_restore_uses_ledger_when_progress_manifest_is_incomplete(self) -> None:
        if _find_powershell() is None:
            self.skipTest("PowerShell executable not available")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = _make_workshop(root)
            gates = root / "gates"

            deployed = _run_ps(
                ["-GatesRoot", str(gates), "-WorkshopRoot", str(workshop)]
            )
            self.assertEqual(deployed.returncode, 0, deployed.stdout + deployed.stderr)

            installed = (
                gates
                / "resource"
                / "set"
                / "multiplayer"
                / "armies"
                / "goc_dprk.set"
            )
            self.assertTrue(installed.is_file())

            manifest = BACKUP / "deployed-files.txt"
            self.assertTrue(manifest.is_file())
            lines = manifest.read_text(encoding="utf-8-sig").splitlines()
            trimmed = [line for line in lines if not line.endswith("/goc_dprk.set")]
            self.assertLess(len(trimmed), len(lines), "test did not remove manifest entry")
            manifest.write_text("\n".join(trimmed) + "\n", encoding="utf-8", newline="\n")

            restored = _run_ps(["-GatesRoot", str(gates), "-Restore"])
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
            self.assertFalse(
                installed.exists(),
                "ledgered originally-absent file survived because manifest was incomplete",
            )

    def test_sha256_does_not_require_get_filehash_cmdlet(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8-sig")
        self.assertIn("[Security.Cryptography.SHA256]::Create()", text)
        self.assertIn("ComputeHash", text)
        self.assertIn("ledger is authoritative", text)
        self.assertIn("Assert-BackupTargetsCurrentGates", text)


if __name__ == "__main__":
    unittest.main()
