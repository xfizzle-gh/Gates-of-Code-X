from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .local_discovery import default_campaign_path, detect_launch_paths
from .scenario_selection import (
    ActorChoice,
    active_scenario_label,
    apply_new_campaign_actor,
    new_campaign_scenarios,
    persisted_actor_id,
    scenario_actor_choices,
)
from .state_io import load_campaign, save_campaign
from .strategic_actors import EngineTacticalSide


@dataclass(frozen=True, slots=True)
class ContinueSummary:
    campaign_path: str
    scenario_id: str
    scenario_label: str
    actor_id: str


class CampaignMenuModel:
    """Headless model used by the player-facing New Campaign / Continue menu."""

    def scenarios(self) -> tuple[tuple[str, str], ...]:
        return tuple((choice.scenario_id, choice.display_name) for choice in new_campaign_scenarios())

    def actors(self, scenario_id: str) -> tuple[ActorChoice, ...]:
        return scenario_actor_choices(scenario_id)

    def playable_actors(self, scenario_id: str) -> tuple[ActorChoice, ...]:
        return tuple(choice for choice in self.actors(scenario_id) if choice.playable)

    def continue_summary(self, campaign_path: str | Path) -> ContinueSummary:
        source = Path(str(campaign_path).strip()).expanduser().resolve(strict=False)
        state = load_campaign(source)
        profile = state.map_metadata.get("scenario_profile")
        if isinstance(profile, Mapping):
            scenario_id = str(profile.get("scenario_id") or "").strip()
        else:
            scenario_id = ""
        scenario_id = scenario_id or str(state.map_metadata.get("scenario_id") or "").strip()
        if not scenario_id:
            raise ValueError("persisted_scenario_id_missing")
        return ContinueSummary(
            campaign_path=str(source),
            scenario_id=scenario_id,
            scenario_label=active_scenario_label(state),
            actor_id=persisted_actor_id(state),
        )


def campaign_faction_for_choice(choice: ActorChoice) -> str:
    """Map an engine tactical identity onto the four-seat campaign authority."""

    return EngineTacticalSide(choice.tactical_side).campaign_faction().value


def _launch_new(
    *,
    scenario_id: str,
    actor_id: str,
    campaign_path: str,
    stack_config: str,
    game_directory: str,
    profile_directory: str,
    godot_executable: str,
    godot_project: str,
) -> ContinueSummary:
    from .player_shell import (
        create_new_campaign,
        find_godot_executable,
        godot_project_directory,
        launch_strategic_application,
        publish_snapshot,
        resolve_campaign_paths,
        write_last_campaign,
    )

    model = CampaignMenuModel()
    choice = next(
        (candidate for candidate in model.playable_actors(scenario_id) if candidate.actor_id == actor_id),
        None,
    )
    if choice is None:
        raise ValueError(f"actor_not_playable:{scenario_id}:{actor_id}")
    paths = resolve_campaign_paths(campaign_path.strip() or None, scenario_id=scenario_id)
    state = create_new_campaign(
        paths=paths,
        scenario_id=scenario_id,
        faction=campaign_faction_for_choice(choice),
        stack_config=stack_config.strip() or None,
        game_directory=game_directory.strip() or None,
        profile_directory=profile_directory.strip() or None,
        force=False,
    )
    apply_new_campaign_actor(state, scenario_id, actor_id)
    save_campaign(state, paths.campaign)
    snapshot = publish_snapshot(state, paths)
    write_last_campaign(paths.campaign)
    executable = find_godot_executable(godot_executable.strip() or None)
    project = godot_project_directory(godot_project.strip() or None)
    launch_strategic_application(
        snapshot=snapshot,
        godot_executable=executable,
        project_directory=project,
    )
    return CampaignMenuModel().continue_summary(paths.campaign)


def _launch_continue(
    *,
    campaign_path: str,
    godot_executable: str,
    godot_project: str,
) -> ContinueSummary:
    from .player_shell import (
        continue_campaign,
        find_godot_executable,
        godot_project_directory,
        launch_strategic_application,
        publish_snapshot,
        resolve_campaign_paths,
        write_last_campaign,
    )

    source = Path(campaign_path.strip()).expanduser().resolve(strict=False)
    before = CampaignMenuModel().continue_summary(source)
    paths = resolve_campaign_paths(source)
    state = continue_campaign(paths=paths)
    after_scenario = active_scenario_label(state)
    after_actor = persisted_actor_id(state)
    if after_scenario != before.scenario_label or after_actor != before.actor_id:
        raise ValueError("continue_changed_persisted_scenario_identity")
    snapshot = publish_snapshot(state, paths)
    write_last_campaign(paths.campaign)
    executable = find_godot_executable(godot_executable.strip() or None)
    project = godot_project_directory(godot_project.strip() or None)
    launch_strategic_application(
        snapshot=snapshot,
        godot_executable=executable,
        project_directory=project,
    )
    return CampaignMenuModel().continue_summary(paths.campaign)


def main() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    model = CampaignMenuModel()
    scenarios = model.scenarios()
    scenario_by_label = {label: scenario_id for scenario_id, label in scenarios}

    root = tk.Tk()
    root.title("Gates of CodeX - Campaign")
    root.geometry("760x690")
    root.minsize(680, 620)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text="Gates of CodeX", font=("Segoe UI", 20, "bold")).pack(anchor=tk.W)
    ttk.Label(
        frame,
        text="Start a 2028 campaign or continue the exact saved scenario and actor.",
    ).pack(anchor=tk.W, pady=(2, 18))

    notebook = ttk.Notebook(frame)
    notebook.pack(fill=tk.BOTH, expand=True)
    new_tab = ttk.Frame(notebook, padding=16)
    continue_tab = ttk.Frame(notebook, padding=16)
    notebook.add(new_tab, text="New Campaign")
    notebook.add(continue_tab, text="Continue")

    scenario_var = tk.StringVar(value=scenarios[0][1] if scenarios else "")
    actor_var = tk.StringVar()
    campaign_var = tk.StringVar()
    stack_var = tk.StringVar()
    game_var = tk.StringVar()
    profile_var = tk.StringVar()
    godot_var = tk.StringVar()
    project_var = tk.StringVar()
    continue_path_var = tk.StringVar()
    status_var = tk.StringVar(value="Scanning local install...")
    continue_status_var = tk.StringVar(
        value="Continue restores the persisted scenario and playable nation without asking again."
    )

    def row(
        parent,
        label: str,
        variable: tk.StringVar,
        *,
        directory: bool = False,
        save_file: bool = False,
    ) -> None:
        container = ttk.Frame(parent)
        container.pack(fill=tk.X, pady=4)
        ttk.Label(container, text=label, width=18).pack(side=tk.LEFT)
        ttk.Entry(container, textvariable=variable).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse() -> None:
            if directory:
                value = filedialog.askdirectory()
            elif save_file:
                value = filedialog.asksaveasfilename(
                    defaultextension=".json",
                    filetypes=(("JSON", "*.json"), ("All files", "*.*")),
                )
            else:
                value = filedialog.askopenfilename()
            if value:
                variable.set(value.strip())

        ttk.Button(container, text="Browse", command=browse).pack(side=tk.LEFT, padx=(6, 0))

    ttk.Label(new_tab, text="Scenario").pack(anchor=tk.W)
    scenario_box = ttk.Combobox(
        new_tab,
        state="readonly",
        textvariable=scenario_var,
        values=[label for _, label in scenarios],
    )
    scenario_box.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(new_tab, text="Playable actor").pack(anchor=tk.W)
    actor_box = ttk.Combobox(new_tab, state="readonly", textvariable=actor_var)
    actor_box.pack(fill=tk.X, pady=(0, 8))

    actor_by_label: dict[str, ActorChoice] = {}

    def refresh_actors(*_args: Any) -> None:
        scenario_id = scenario_by_label.get(scenario_var.get(), "")
        choices = model.playable_actors(scenario_id) if scenario_id else ()
        actor_by_label.clear()
        for choice in choices:
            actor_by_label[choice.display_name] = choice
        labels = list(actor_by_label)
        actor_box.configure(values=labels)
        actor_var.set(labels[0] if labels else "")
        if scenario_id:
            campaign_var.set(str(default_campaign_path(scenario_id)))

    scenario_box.bind("<<ComboboxSelected>>", refresh_actors)
    refresh_actors()

    def scan_local_install() -> None:
        scenario_id = scenario_by_label.get(scenario_var.get(), "")
        if not scenario_id:
            status_var.set("Choose a scenario before scanning.")
            return
        try:
            discovered = detect_launch_paths(scenario_id)
        except Exception as exc:
            status_var.set(f"Auto-detect failed: {exc}")
            return

        for key, value in discovered.environment:
            os.environ[key] = value

        campaign_var.set(discovered.campaign_file)
        if discovered.stack_config:
            stack_var.set(discovered.stack_config)
        if discovered.game_directory:
            game_var.set(discovered.game_directory)
        if discovered.profile_directory:
            profile_var.set(discovered.profile_directory)
        if discovered.godot_executable:
            godot_var.set(discovered.godot_executable)
        if discovered.godot_project:
            project_var.set(discovered.godot_project)
        if discovered.continue_campaign_file:
            continue_path_var.set(discovered.continue_campaign_file)

        status_var.set(discovered.status_message())

    ttk.Button(
        new_tab,
        text="Scan local install",
        command=scan_local_install,
    ).pack(anchor=tk.W, pady=(0, 8))

    row(new_tab, "Campaign file", campaign_var, save_file=True)
    row(new_tab, "Stack config", stack_var)
    row(new_tab, "Game directory", game_var, directory=True)
    row(new_tab, "Profile directory", profile_var, directory=True)
    row(new_tab, "Godot executable", godot_var)
    row(new_tab, "Godot project", project_var, directory=True)

    ttk.Label(new_tab, textvariable=status_var, wraplength=660).pack(anchor=tk.W, pady=(12, 8))

    def launch_new() -> None:
        scenario_id = scenario_by_label.get(scenario_var.get(), "")
        choice = actor_by_label.get(actor_var.get())
        if not scenario_id or choice is None:
            messagebox.showerror("New Campaign", "Choose a scenario and playable actor.")
            return
        try:
            summary = _launch_new(
                scenario_id=scenario_id,
                actor_id=choice.actor_id,
                campaign_path=campaign_var.get().strip(),
                stack_config=stack_var.get().strip(),
                game_directory=game_var.get().strip(),
                profile_directory=profile_var.get().strip(),
                godot_executable=godot_var.get().strip(),
                godot_project=project_var.get().strip(),
            )
        except Exception as exc:
            messagebox.showerror("New Campaign", str(exc))
            return
        status_var.set(
            f"Created {summary.scenario_label} as {summary.actor_id}; strategic screen launched."
        )
        continue_path_var.set(summary.campaign_path)

    ttk.Button(new_tab, text="Start Campaign", command=launch_new).pack(anchor=tk.W)

    row(continue_tab, "Campaign file", continue_path_var)
    ttk.Label(continue_tab, textvariable=continue_status_var, wraplength=660).pack(
        anchor=tk.W, pady=(12, 8)
    )

    def inspect_continue() -> None:
        try:
            summary = model.continue_summary(continue_path_var.get().strip())
        except Exception as exc:
            messagebox.showerror("Continue", str(exc))
            return
        continue_status_var.set(
            f"Scenario: {summary.scenario_label}\nPlayable nation: {summary.actor_id}\n"
            "Continue will reuse this persisted selection."
        )

    def launch_continue() -> None:
        try:
            summary = _launch_continue(
                campaign_path=continue_path_var.get().strip(),
                godot_executable=godot_var.get().strip(),
                godot_project=project_var.get().strip(),
            )
        except Exception as exc:
            messagebox.showerror("Continue", str(exc))
            return
        continue_status_var.set(
            f"Continuing {summary.scenario_label} as {summary.actor_id}; strategic screen launched."
        )

    ttk.Button(continue_tab, text="Inspect Save", command=inspect_continue).pack(anchor=tk.W)
    ttk.Button(continue_tab, text="Continue Campaign", command=launch_continue).pack(
        anchor=tk.W, pady=(6, 0)
    )

    root.after(0, scan_local_install)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
