from __future__ import annotations

import argparse
import cProfile
import pstats
import time
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import earth3_bootstrap, observation
from gates_of_codex.state_io import load_campaign


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Profile CampaignState.validate base work without nested Earth3/S11 validators."
    )
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    state = load_campaign(args.campaign)
    profile = cProfile.Profile()
    started = time.perf_counter()
    with (
        patch.object(
            earth3_bootstrap,
            "validate_earth3_bootstrap_campaign_state",
            lambda _state: None,
        ),
        patch.object(
            observation,
            "validate_s11_observer_authority",
            lambda _state: None,
        ),
    ):
        profile.enable()
        state.validate()
        profile.disable()
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    stats = pstats.Stats(profile)
    rows = []
    for (filename, lineno, function), values in stats.stats.items():
        primitive_calls, total_calls, self_seconds, cumulative_seconds, _callers = values
        rows.append(
            (
                cumulative_seconds,
                self_seconds,
                primitive_calls,
                total_calls,
                Path(filename).name,
                lineno,
                function,
            )
        )
    rows.sort(reverse=True)

    print(f"VALIDATION_BASE_PROFILE total_ms={elapsed_ms:.3f}")
    print("VALIDATION_BASE_PROFILE top_cumulative")
    for cumulative, self_seconds, primitive_calls, total_calls, filename, lineno, function in rows[: args.limit]:
        print(
            "  "
            f"cum_ms={cumulative * 1000.0:.3f} "
            f"self_ms={self_seconds * 1000.0:.3f} "
            f"pcalls={primitive_calls} calls={total_calls} "
            f"{filename}:{lineno}:{function}"
        )

    rows.sort(key=lambda row: row[1], reverse=True)
    print("VALIDATION_BASE_PROFILE top_self")
    for cumulative, self_seconds, primitive_calls, total_calls, filename, lineno, function in rows[: args.limit]:
        print(
            "  "
            f"self_ms={self_seconds * 1000.0:.3f} "
            f"cum_ms={cumulative * 1000.0:.3f} "
            f"pcalls={primitive_calls} calls={total_calls} "
            f"{filename}:{lineno}:{function}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
