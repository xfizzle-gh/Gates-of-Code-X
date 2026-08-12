from gates_of_codex.frozen_runtime import configure_frozen_earth3_authority


def _authenticate_frozen_earth3() -> None:
    root = configure_frozen_earth3_authority()
    if root is None:
        return

    from gates_of_codex.earth3_campaign import load_earth3_authority
    from gates_of_codex.earth3_operational import load_authenticated_p3_graph

    p1 = load_earth3_authority()
    p3 = load_authenticated_p3_graph()
    if p1.production_asset_version != "earth3_production_v1":
        raise RuntimeError("Frozen Earth3 P1 production authority version mismatch")
    if len(p3.get("nodes", [])) != 64 or len(p3.get("edges", [])) != 65:
        raise RuntimeError("Frozen Earth3 P3 operational authority count mismatch")


if __name__ == "__main__":
    _authenticate_frozen_earth3()
    from gates_of_codex.acceptance_cli import main

    raise SystemExit(main())
