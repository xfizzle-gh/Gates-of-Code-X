from __future__ import annotations

"""Refresh safe warm-Continue proof after a full validated relaunch.

The #221 daemon intentionally pins its original campaign and snapshot fingerprints
so a gameplay mutation cannot accidentally reuse a stale on-disk snapshot. After
that mutation, the next full player launch validates the campaign and republishes
(or byte-proves) the canonical frontend snapshot. Record that exact pair as a
new derived launch baseline so the already-healthy daemon can serve later warm
Continues without being restarted or weakening file/source provenance checks.
"""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


REBASELINE_SCHEMA = "gates-of-codex.startup-rebaseline"
REBASELINE_VERSION = 1
REBASELINE_DIRECTORY_NAME = "startup_rebaseline"

_INSTALLED = False


def _marker_path(campaign: Path, snapshot: Path) -> Path:
    from .player_shell import player_home

    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    identity = hashlib.sha256(
        (str(campaign) + "\0" + str(snapshot)).encode("utf-8")
    ).hexdigest()
    return player_home() / REBASELINE_DIRECTORY_NAME / f"{identity}.json"


def _current_maintenance_signature(
    campaign: Path,
    *,
    environ=None,
) -> str:
    from .startup_cold_optimizations import _maintenance_signature

    return _maintenance_signature(campaign, environ=environ)


def _fingerprint_record(persistent_backend, path: Path) -> dict[str, Any]:
    size, mtime_ns, sha256 = persistent_backend._fingerprint(path)
    return {
        "size": int(size),
        "mtime_ns": int(mtime_ns),
        "sha256": str(sha256),
    }


def _write_rebaseline_marker(
    persistent_backend,
    campaign: Path,
    snapshot: Path,
    *,
    environ=None,
) -> bool:
    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    source_commit = persistent_backend._runtime_source_commit()
    if source_commit is None or not campaign.is_file() or not snapshot.is_file():
        return False
    try:
        payload = {
            "schema": REBASELINE_SCHEMA,
            "schema_version": REBASELINE_VERSION,
            "source_commit": source_commit,
            "campaign_path": str(campaign),
            "snapshot_path": str(snapshot),
            "maintenance_signature": _current_maintenance_signature(
                campaign,
                environ=environ,
            ),
            "campaign": _fingerprint_record(persistent_backend, campaign),
            "snapshot": _fingerprint_record(persistent_backend, snapshot),
        }
        destination = _marker_path(campaign, snapshot)
        destination.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary.write(body)
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _marker_metadata_matches(
    persistent_backend,
    campaign: Path,
    snapshot: Path,
    *,
    environ=None,
) -> bool:
    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    source_commit = persistent_backend._runtime_source_commit()
    if source_commit is None:
        return False
    source = _marker_path(campaign, snapshot)
    if not source.is_file():
        return False
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            return False
        if payload.get("schema") != REBASELINE_SCHEMA:
            return False
        if int(payload.get("schema_version", 0) or 0) != REBASELINE_VERSION:
            return False
        if str(payload.get("source_commit", "")) != source_commit:
            return False
        if str(payload.get("campaign_path", "")) != str(campaign):
            return False
        if str(payload.get("snapshot_path", "")) != str(snapshot):
            return False
        current_maintenance = _current_maintenance_signature(
            campaign,
            environ=environ,
        )
        return str(payload.get("maintenance_signature", "")) == current_maintenance
    except (OSError, TypeError, ValueError):
        return False


def _rebaseline_marker_matches(
    persistent_backend,
    campaign: Path,
    snapshot: Path,
) -> bool:
    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    source = _marker_path(campaign, snapshot)
    if (
        not campaign.is_file()
        or not snapshot.is_file()
        or not _marker_metadata_matches(
            persistent_backend,
            campaign,
            snapshot,
        )
    ):
        return False
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        return (
            isinstance(payload, dict)
            and payload.get("campaign")
            == _fingerprint_record(persistent_backend, campaign)
            and payload.get("snapshot")
            == _fingerprint_record(persistent_backend, snapshot)
        )
    except (OSError, TypeError, ValueError):
        return False


def _rebaseline_response_if_safe(
    persistent_backend,
    response: dict[str, Any],
    *,
    cached_state,
    cached_fingerprint,
    campaign: Path,
    snapshot: Path | None,
) -> dict[str, Any]:
    if response.get("ok") is True:
        return response
    if cached_state is None or cached_fingerprint is None or snapshot is None:
        return response
    try:
        current_campaign_fingerprint = persistent_backend._fingerprint(campaign)
    except OSError:
        return response
    if cached_fingerprint != current_campaign_fingerprint:
        return response
    if not _rebaseline_marker_matches(persistent_backend, campaign, snapshot):
        return response
    return {
        "handled": True,
        "exit_code": 0,
        "ok": True,
        "state": persistent_backend._startup_state_summary(cached_state),
        "rebaseline": True,
    }


def _install_snapshot_rebaseline_marker(player_shell, persistent_backend) -> None:
    current = player_shell.publish_snapshot
    if getattr(current, "_goc_startup_rebaseline_marker", False):
        return

    def publish_with_rebaseline_marker(state, paths, *, environ=None):
        written = current(state, paths, environ=environ)
        _write_rebaseline_marker(
            persistent_backend,
            paths.campaign,
            paths.snapshot,
            environ=environ,
        )
        return written

    publish_with_rebaseline_marker._goc_startup_rebaseline_marker = True
    player_shell.publish_snapshot = publish_with_rebaseline_marker


def _install_daemon_rebaseline_response(persistent_backend) -> None:
    current = persistent_backend._startup_reuse_response
    if getattr(current, "_goc_startup_rebaseline_response", False):
        return

    def startup_reuse_with_rebaseline(**kwargs):
        response = current(**kwargs)
        return _rebaseline_response_if_safe(
            persistent_backend,
            response,
            cached_state=kwargs.get("cached_state"),
            cached_fingerprint=kwargs.get("cached_fingerprint"),
            campaign=kwargs.get("campaign"),
            snapshot=kwargs.get("snapshot"),
        )

    startup_reuse_with_rebaseline._goc_startup_rebaseline_response = True
    persistent_backend._startup_reuse_response = startup_reuse_with_rebaseline


def _install_probe_maintenance_guard(persistent_backend) -> None:
    current = persistent_backend.probe_startup_reuse
    if getattr(current, "_goc_startup_maintenance_guard", False):
        return

    def probe_startup_reuse_with_maintenance(campaign: Path, snapshot: Path):
        state = current(campaign, snapshot)
        if state is None:
            return None
        if not _marker_metadata_matches(
            persistent_backend,
            campaign,
            snapshot,
        ):
            return None
        return state

    probe_startup_reuse_with_maintenance._goc_startup_maintenance_guard = True
    persistent_backend.probe_startup_reuse = probe_startup_reuse_with_maintenance


def _install_canonical_migration_save_guard(player_shell) -> None:
    """Preserve the original Continue contract for campaigns migrated on load.

    The optimized full path may elide an unchanged save. That is safe only when
    the authoritative file was already on the current schema. Capture the raw
    incoming discriminator at the existing JSON parse boundary, without a second
    campaign read, and persist once if load-time migration raised it to schema 11.
    """

    current = player_shell.continue_campaign
    if getattr(current, "_goc_canonical_migration_save_guard", False):
        return

    def continue_with_canonical_migration_save(*args, **kwargs):
        from . import state_io
        from .observation import S11_CAMPAIGN_SCHEMA_VERSION

        paths = kwargs.get("paths")
        original_from_dict = state_io.campaign_from_dict
        incoming_schema: int | None = None

        def capture_incoming_schema(data):
            nonlocal incoming_schema
            try:
                incoming_schema = max(1, int(data.get("schema_version", 1)))
            except (AttributeError, TypeError, ValueError):
                incoming_schema = None
            return original_from_dict(data)

        state_io.campaign_from_dict = capture_incoming_schema
        try:
            state = current(*args, **kwargs)
        finally:
            state_io.campaign_from_dict = original_from_dict

        if (
            paths is not None
            and incoming_schema is not None
            and incoming_schema < S11_CAMPAIGN_SCHEMA_VERSION
        ):
            state_io.save_campaign(state, paths.campaign)
        return state

    continue_with_canonical_migration_save._goc_canonical_migration_save_guard = True
    player_shell.continue_campaign = continue_with_canonical_migration_save


def install_startup_rebaseline_contracts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import persistent_backend, player_shell

    _install_snapshot_rebaseline_marker(player_shell, persistent_backend)
    _install_daemon_rebaseline_response(persistent_backend)
    _install_probe_maintenance_guard(persistent_backend)
    _install_canonical_migration_save_guard(player_shell)
    _INSTALLED = True
