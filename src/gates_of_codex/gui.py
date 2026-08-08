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
        ttk.Button(panel, text="Auto-resolve", command=self.auto_resolve).pack(fill=tk.X)
        ttk.Button(panel, text="Export Battle", command=self.export_battle).pack(fill=tk.X, pady=(12, 4))
        ttk.Button(panel, text="Import Battle", command=self.import_battle).pack(fill=tk.X)
        ttk.Button(panel, text="End Turn", command=self.end_turn).pack(fill=tk.X, pady=(12, 0))
        self.status = ttk.Label(panel, text="Open a campaign", wraplength=260)
        self.status.pack(fill=tk.X, pady=(16, 0))
        self.canvas.bind("<Configure>", lambda _: self.draw())
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

    def save(self, *, observation_context=None) -> None:
        if self.state is None:
            return
        if self.campaign_path is None:
            value = filedialog.asksaveasfilename(defaultextension=".json")
            if not value:
                return
            self.campaign_path = Path(value)
        save_campaign(
            self.state,
            self.campaign_path,
            observation_context=observation_context,
        )
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
        occupied = {b.province_id: b for b in self.state.battalions.values()}
        for province in self.state.provinces.values():
            x, y = province.x * scale_x, province.y * scale_y
            color = FACTION_COLORS.get(province.owner.value, "#777")
            self.canvas.create_oval(x - 28, y - 28, x + 28, y + 28, fill=color, outline="#eee", width=2)
            self.canvas.create_text(x, y + 42, text=province.display_name, fill="white", font=("Segoe UI", 9))
            if province.province_id in occupied:
                self.canvas.create_text(x, y, text=occupied[province.province_id].battalion_id, fill="white", font=("Segoe UI", 8, "bold"))

    def _select_battalion(self, _event=None) -> None:
        selection = self.battalion_list.curselection()
        if self.state is None or not selection:
            return
        self.selected_battalion = list(self.state.battalions)[selection[0]]

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
            engine = CampaignEngine(self.state)
            winner = engine.auto_resolve_pending_battle()
            self.save(observation_context=engine.observation_context)
            self.refresh()
            messagebox.showinfo("Battle resolved", f"Winner: {winner.value}")
        except Exception as exc:
            messagebox.showerror("Resolve failed", str(exc))

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
