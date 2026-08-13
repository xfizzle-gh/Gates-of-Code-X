from __future__ import annotations

"""Refresh safe warm-Continue proof after a full validated relaunch.

The #221 daemon intentionally pins its original campaign and snapshot fingerprints
so a gameplay mutation cannot accidentally reuse a stale on-disk snapshot. After
that mutation, the next full player launch validates the campaign and republishes
(or byte-proves) the canonical frontend snapshot. Record that exact pair as a
new derived launch baseline so the already-healthy daemon can serve later warm
Continues without being restarted or weakening file/source provenance checks.
"""

import json
import tempfile
from pathlib import Path
from typing import Any


REBASELINE_SCHEMA = "gates-of-codex.startup-rebaseline"
REBASELINE_VERSION = 1
REBASELINE_FILE_NAME = ".goc-startup-rebaseline.json"

_INSTALLED = False


def _marker_path(snapshot: Path) -> Path:
    return snapshot.expanduser().resolve(strict=False).with_name(REBASELINE_FILE_NAME)


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
            "campaign": _fingerprint_record(persistent_backend, campaign),
            "snapshot": _fingerprint_record(persistent_backend, snapshot),
        }
        destination = _marker_path(snapshot)
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


def _rebaseline_marker_matches(
    persistent_backend,
    campaign: Path,
    snapshot: Path,
) -> bool:
    campaign = campaign.expanduser().resolve(strict=False)
    snapshot = snapshot.expanduser().resolve(strict=False)
    source_commit = persistent_backend._runtime_source_commit()
    if source_commit is None:
        return False
    source = _marker_path(snapshot)
    if not source.is_file() or not campaign.is_file() or not snapshot.is_file():
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
        return (
            payload.get("campaign") == _fingerprint_record(persistent_backend, campaign)
            and payload.get("snapshot") == _fingerprint_record(persistent_backend, snapshot)
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


def install_startup_rebaseline_contracts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import persistent_backend, player_shell

    _install_snapshot_rebaseline_marker(player_shell, persistent_backend)
    _install_daemon_rebaseline_response(persistent_backend)
    _INSTALLED = True
