from __future__ import annotations

"""Repair the frozen nonblocking backend spawn identity boundary.

The #221 cold-start shortcut launches the sibling console backend before first
paint. Frozen ``session-backend`` entrypoints require the caller-selected source
commit, just like ``apply-frontend``. The original nonblocking helper omitted
that flag, so the child correctly failed closed before publishing its session
file. Install the corrected frozen helper at the packaged player boundary while
leaving source/non-frozen behavior unchanged.
"""

from pathlib import Path


_INSTALLED = False


def install_packaged_backend_spawn_identity() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import startup_cold_optimizations as cold

    original = cold._begin_backend_session_nonblocking
    if getattr(original, "_goc_authenticated_frozen_spawn", False):
        _INSTALLED = True
        return

    def authenticated_begin_backend_session_nonblocking(
        persistent_backend,
        campaign: Path,
        snapshot: Path,
    ) -> bool:
        if not bool(getattr(cold.sys, "frozen", False)):
            return original(persistent_backend, campaign, snapshot)

        campaign = campaign.expanduser().resolve(strict=False)
        snapshot = snapshot.expanduser().resolve(strict=False)
        key = str(campaign)
        source_commit = persistent_backend._runtime_source_commit()
        if source_commit is None:
            persistent_backend._drop_session_descriptor(campaign)
            cold._BACKEND_STARTING.discard(key)
            return False
        if persistent_backend._ping(campaign):
            cold._BACKEND_STARTING.discard(key)
            return True
        if key in cold._BACKEND_STARTING:
            return False

        persistent_backend._drop_session_descriptor(campaign)
        executable = Path(cold.sys.executable).resolve().with_name("GatesOfCodeXLive.exe")
        command = [
            str(executable),
            "session-backend",
            str(campaign),
            "--snapshot",
            str(snapshot),
            "--expected-source-commit",
            str(source_commit),
        ]
        creationflags = (
            int(getattr(cold.subprocess, "CREATE_NO_WINDOW", 0))
            if cold.os.name == "nt"
            else 0
        )
        started = cold.time.perf_counter()
        try:
            cold.subprocess.Popen(
                command,
                cwd=str(campaign.parent),
                stdin=cold.subprocess.DEVNULL,
                stdout=cold.subprocess.DEVNULL,
                stderr=cold.subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError:
            cold._emit(
                "persistent_backend_spawn",
                duration_ms=(cold.time.perf_counter() - started) * 1000.0,
                started=False,
            )
            return False
        cold._BACKEND_STARTING.add(key)
        cold._emit(
            "persistent_backend_spawn",
            duration_ms=(cold.time.perf_counter() - started) * 1000.0,
            started=True,
        )
        return False

    authenticated_begin_backend_session_nonblocking._goc_authenticated_frozen_spawn = True  # type: ignore[attr-defined]
    cold._begin_backend_session_nonblocking = authenticated_begin_backend_session_nonblocking
    _INSTALLED = True
