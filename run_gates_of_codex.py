import os
import time


os.environ.setdefault("GATES_OF_CODEX_STARTUP_TELEMETRY", "1")
os.environ.setdefault(
    "GATES_OF_CODEX_STARTUP_EPOCH_MS",
    f"{time.time() * 1000.0:.3f}",
)

from gates_of_codex.fast_entrypoint import player_main


if __name__ == "__main__":
    raise SystemExit(player_main())
