from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .campaign import CampaignEngine
from .service import GatesOfCodeXService
from .state_io import load_campaign, save_campaign


FACTION_COLORS = {
    "nato": "#3977d5",
    "ukr": "#e5bc30",
    "rusa": "#c84747",
    "prc": "#b02b2b",
    "neutral": "#777777",
}


class CampaignApp(tk.Tk):
    def __init__(self, campaign_path: str | Path | None = None) -> None:
        super().__init__()
        self.title("Gates of CodeX")
        self.geometry("1280x720")
        self.campaign_path: Path | None = None
        self.state = None
        self.selected_battalion: str | None = None
        self.canvas = tk.Canvas(self, bg="#15181d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        panel = ttk.Frame(self, padding=10)
        panel.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(panel, text="Open", command=self.open_campaign).pack(fill=tk.X)
        ttk.Button(panel, text="Save", command=self.save).pack(fill=tk.X, pady=(4, 12))
        ttk.Label(panel, text="Battalions").pack(anchor=tk.W)
        self.battalion_list = tk.Listbox(panel, width=35, height=18)
        self.battalion_list.pack(fill=tk.BOTH, expand=True)
        self.battalion_list.bind("<<ListboxSelect>>", self._select_battalion)
        ttk.Button(panel, text="Move / Attack", command=self.move).pack(fill=tk.X, pady=(12, 4))
        ttk.Button(panel, text="Auto-resolve (A)", command=self.auto_resolve).pack(fill=tk.X)
        ttk.Button(panel, text="Next turn", command=self.next_turn).pack(fill=tk.X, pady=(12, 4))
        ttk.Button(panel, text="Auto-play NATO turn", command=self.autoplay_turn).pack(fill=tk.X)
        ttk.Button(panel, text="Fight in GoH (optional)", command=self.fight_in_goh).pack(fill=tk.X, pady=(12, 4))
        ttk.Button(panel, text="Export Battle", command=self.export_battle).pack(fill=tk.X)
        ttk.Button(panel, text="Import Battle", command=self.import_battle).pack(fill=tk.X)
        ttk.Button(panel, text="End Turn", command=self.end_turn).pack(fill=tk.X, pady=(12, 0))
        self.status = ttk.Label(panel, text="Open a campaign — click a unit, then a highlighted neighbor", wraplength=260)
        self.status.pack(fill=tk.X, pady=(16, 0))
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Button-1>", self._click_map)
        if campaign_path:
            self.load(Path(campaign_path))

    def load(self, path: Path) -> None:
        try:
            self.state = load_campaign(path)
            self.campaign_path = path
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def open_campaign(self) -> None:
        value = filedialog.askopenfilename(filetypes=[("Campaign JSON", "*.json"), ("All files", "*")])
        if value:
            self.load(Path(value))

    def save(self) -> None:
        if self.state is None:
            return
        if self.campaign_path is None:
            value = filedialog.asksaveasfilename(defaultextension=".json")
            if not value:
                return
            self.campaign_path = Path(value)
        save_campaign(self.state, self.campaign_path)
        self.status.config(text=f"Saved {self.campaign_path}")

    def refresh(self) -> None:
        self.battalion_list.delete(0, tk.END)
        if self.state is None:
            return
        for battalion in self.state.battalions.values():
            self.battalion_list.insert(tk.END, f"{battalion.battalion_id} | {battalion.faction.value} | {battalion.province_id} | {battalion.unit_count}")
        pending = self.state.pending_battle.battle_id if self.state.pending_battle else "none"
        self.status.config(text=f"Turn {self.state.turn_number} | {self.state.current_faction.value} | pending: {pending}")
        self.draw()

    def draw(self) -> None:
        self.canvas.delete("all")
        if self.state is None:
            return
        scale_x = max(self.canvas.winfo_width() / 1300, 0.6)
        scale_y = max(self.canvas.winfo_height() / 650, 0.6)
        for province in self.state.provinces.values():
            for neighbor_id in province.neighbors:
                if province.province_id < neighbor_id:
                    neighbor = self.state.provinces[neighbor_id]
                    self.canvas.create_line(province.x * scale_x, province.y * scale_y, neighbor.x * scale_x, neighbor.y * scale_y, fill="#555", width=3)
        from .play_context import list_front_options

        occupied = {b.province_id: b for b in self.state.battalions.values()}
        targets = {
            row["target"]: row["kind"]
            for row in list_front_options(self.state)
            if self.selected_battalion and row["battalion_id"] == self.selected_battalion
        }
        selected_province = ""
        if self.selected_battalion and self.selected_battalion in self.state.battalions:
            selected_province = self.state.battalions[self.selected_battalion].province_id
        for province in self.state.provinces.values():
            x, y = province.x * scale_x, province.y * scale_y
            color = FACTION_COLORS.get(province.owner.value, "#777")
            kind = targets.get(province.province_id)
            outline = "#eee"
            width = 2
            if province.province_id == selected_province:
                outline, width = "#ffffff", 4
            elif kind in {"battle", "capture"}:
                outline, width = "#ff9f43", 4
            elif kind:
                outline, width = "#3dff8a", 3
            self.canvas.create_oval(x - 28, y - 28, x + 28, y + 28, fill=color, outline=outline, width=width)
            self.canvas.create_text(x, y + 42, text=province.display_name, fill="white", font=("Segoe UI", 9))
            if province.province_id in occupied:
                self.canvas.create_text(x, y, text=occupied[province.province_id].battalion_id, fill="white", font=("Segoe UI", 8, "bold"))

    def _select_battalion(self, _event=None) -> None:
        selection = self.battalion_list.curselection()
        if self.state is None or not selection:
            return
        self.selected_battalion = list(self.state.battalions)[selection[0]]
        self.draw()

    def _click_map(self, event) -> None:
        if self.state is None:
            return
        province_id = self._province_at(event.x, event.y)
        if not province_id:
            return
        from .play_context import list_front_options

        if self.selected_battalion:
            match = next(
                (
                    row
                    for row in list_front_options(self.state)
                    if row["battalion_id"] == self.selected_battalion and row["target"] == province_id
                ),
                None,
            )
            if match:
                try:
                    CampaignEngine(self.state).move_or_attack(self.selected_battalion, province_id)
                    self.save()
                    self.refresh()
                    if self.state.pending_battle is not None:
                        self.status.config(text="Pending battle — Auto-resolve or Fight in GoH")
                except Exception as exc:
                    messagebox.showerror("Move failed", str(exc))
                return
        occupant = next(
            (
                battalion
                for battalion in self.state.battalions.values()
                if battalion.province_id == province_id and battalion.faction == self.state.current_faction
            ),
            None,
        )
        if occupant is not None:
            self.selected_battalion = occupant.battalion_id
            keys = list(self.state.battalions)
            if occupant.battalion_id in keys:
                index = keys.index(occupant.battalion_id)
                self.battalion_list.selection_clear(0, tk.END)
                self.battalion_list.selection_set(index)
                self.battalion_list.see(index)
            self.draw()

    def _province_at(self, x: float, y: float) -> str | None:
        if self.state is None:
            return None
        scale_x = max(self.canvas.winfo_width() / 1300, 0.6)
        scale_y = max(self.canvas.winfo_height() / 650, 0.6)
        best_id = None
        best_distance = 36.0
        for province in self.state.provinces.values():
            px, py = province.x * scale_x, province.y * scale_y
            distance = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if distance < best_distance:
                best_distance = distance
                best_id = province.province_id
        return best_id

    def move(self) -> None:
        if self.state is None or not self.selected_battalion:
            messagebox.showinfo("Move", "Select a battalion first")
            return
        target = simpledialog.askstring("Move / Attack", "Target province ID:")
        if not target:
            return
        try:
            CampaignEngine(self.state).move_or_attack(self.selected_battalion, target)
            self.save()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Move failed", str(exc))

    def auto_resolve(self) -> None:
        if self.state is None:
            return
        try:
            winner = CampaignEngine(self.state).auto_resolve_pending_battle()
            self.save()
            self.refresh()
            messagebox.showinfo("Battle resolved", f"Winner: {winner.value}")
        except Exception as exc:
            messagebox.showerror("Resolve failed", str(exc))

    def next_turn(self) -> None:
        if self.state is None or self.campaign_path is None:
            return
        try:
            from .campaign_loop import finish_player_overmap_turn

            payload = finish_player_overmap_turn(self.campaign_path)
            self.load(self.campaign_path)
            messagebox.showinfo(
                "Next turn",
                f"Turn {payload.get('turn_number')} | {payload.get('current_faction')}",
            )
        except Exception as exc:
            messagebox.showerror("Next turn failed", str(exc))

    def autoplay_turn(self) -> None:
        if self.state is None or self.campaign_path is None:
            return
        try:
            from .campaign_loop import overmap_turn

            payload = overmap_turn(self.campaign_path)
            self.load(self.campaign_path)
            messagebox.showinfo(
                "Auto-play",
                f"Turn {payload.get('turn_number')} | {payload.get('current_faction')}",
            )
        except Exception as exc:
            messagebox.showerror("Auto-play failed", str(exc))

    def continue_campaign(self) -> None:
        self.next_turn()

    def fight_in_goh(self) -> None:
        if self.state is None or self.campaign_path is None:
            return
        try:
            from .front_attack import attack_front

            payload = attack_front(self.campaign_path, export=True)
            self.load(self.campaign_path)
            save = payload.get("save") or "gatesofcodex.sav"
            messagebox.showinfo(
                "Fight in GoH",
                payload.get("load_instruction") or f"Load Conquest: GatesOfCodeX\n{save}",
            )
        except Exception as exc:
            messagebox.showerror("Fight in GoH failed", str(exc))

    def export_battle(self) -> None:
        if self.state is None or self.campaign_path is None:
            return
        save_path = filedialog.asksaveasfilename(defaultextension=".sav")
        if not save_path:
            return
        map_name = simpledialog.askstring("Map", "GoH map identifier:")
        if not map_name:
            return
        codex = self.state.code_x_directory or filedialog.askdirectory(title="Select Code:X directory")
        try:
            GatesOfCodeXService().export_battle(self.campaign_path, code_x_directory=codex, save_path=save_path, map_name=map_name)
            self.load(self.campaign_path)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    def import_battle(self) -> None:
        if self.state is None or self.campaign_path is None:
            return
        save_path = filedialog.askopenfilename(filetypes=[("GoH save", "*.sav"), ("All files", "*")])
        if not save_path:
            return
        try:
            result = GatesOfCodeXService().import_battle(self.campaign_path, save_path=save_path)
            self.load(self.campaign_path)
            messagebox.showinfo("Imported", f"Winner: {result.winner.value}")
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))

    def end_turn(self) -> None:
        if self.state is None:
            return
        try:
            CampaignEngine(self.state).end_turn()
            self.save()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("End turn failed", str(exc))


def main(campaign_path: str | Path | None = None) -> None:
    CampaignApp(campaign_path).mainloop()
