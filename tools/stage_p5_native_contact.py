from __future__ import annotations

import argparse
import json
from pathlib import Path

from gates_of_codex.native_acceptance import stage_player_one_hop_from_rusa
from gates_of_codex.state_io import load_campaign, save_campaign


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a fresh Earth3 P5 native-test campaign one approved hop from RUSA."
    )
    parser.add_argument("--campaign", required=True, help="Path to authoritative campaign.json")
    args = parser.parse_args()

    campaign = Path(args.campaign).expanduser().resolve()
    if not campaign.is_file():
        parser.error(f"campaign does not exist: {campaign}")

    state = load_campaign(campaign)
    staged = stage_player_one_hop_from_rusa(state)
    save_campaign(state, campaign)
    print(json.dumps(staged.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
