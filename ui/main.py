import os
import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import DEFAULT_FLOW_RATE
from sumo.net_builder import build_network
from sumo.route_builder import generate_routes_from_network

GEOMETRY_FILE = os.path.join(PROJECT_ROOT, "osm", "geometry.json")
NET_FILE = os.path.join(PROJECT_ROOT, "sumo", "test_intersection.net.xml")
ROUTES_FILE = os.path.join(PROJECT_ROOT, "sumo", "routes.rou.xml")
CONFIG_FILE = os.path.join(PROJECT_ROOT, "sumo", "intersection.sumocfg")

ALL_MANEUVERS = ["left", "through", "right"]


def angle_to_direction(angle_deg):
    """
    Преобразует угол (направление от центра перекрёстка) в направление подхода к центру.
    Например, угол 298° (выезд на СЗ) -> подход с ЮВ (ЮВ-центр).
    """
    approach_angle = (angle_deg + 180) % 360
    dirs = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    idx = round(approach_angle / 45) % 8
    return f"{dirs[idx]}-центр"


class ApproachEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Редактор направлений полос и интенсивности")
        self.root.geometry("1200x700")

        self.approaches = []
        self.groups = {}
        self.current_group_key = None
        self.item_to_key = {}

        self.load_data()
        if not self.approaches:
            messagebox.showerror("Ошибка", f"Не найден или пуст {GEOMETRY_FILE}")
            self.root.destroy()
            return

        self.build_gui()

    def load_data(self):
        if not os.path.exists(GEOMETRY_FILE):
            return
        with open(GEOMETRY_FILE, "r", encoding="utf-8") as f:
            self.approaches = json.load(f)

        self.groups = {}
        for app in self.approaches:
            name = app.get("street_name", "Без названия")
            angle = app.get("angle_deg", 0)
            key = (name, angle)
            if key not in self.groups:
                self.groups[key] = {
                    "street_name": name,
                    "angle_deg": angle,
                    "lanes_in": 0,
                    "lanes_out": 0,
                    "turn_lanes": [],
                    "lane_flow_rates": [],
                    "traffic_lights": [],
                    "has_in": False,
                    "has_out": False,
                    "in_app": None,
                    "out_app": None
                }
            group = self.groups[key]
            if app["direction"] == "ВЪЕЗД":
                group["has_in"] = True
                group["lanes_in"] = app.get("lanes", 0)
                group["turn_lanes"] = app.get("turn_lanes", [])
                group["lane_flow_rates"] = app.get("lane_flow_rates", [DEFAULT_FLOW_RATE] * group["lanes_in"])
                group["traffic_lights"] = app.get("traffic_lights", [])
                group["in_app"] = app
            elif app["direction"] == "ВЫЕЗД":
                group["has_out"] = True
                group["lanes_out"] = app.get("lanes", 0)
                group["out_app"] = app

    def build_gui(self):
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=1)
        ttk.Label(left_frame, text="Список подходов", font=("Arial", 12)).pack(pady=5)

        columns = ("Улица", "Направление", "Въезд (полос)", "Выезд (полос)")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150, anchor=tk.CENTER)
        self.tree.column("Направление", width=120)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        for key, group in self.groups.items():
            name, angle = key
            direction = angle_to_direction(angle)
            values = (
                name,
                direction,
                str(group["lanes_in"]) if group["has_in"] else "-",
                str(group["lanes_out"]) if group["has_out"] else "-",
            )
            item = self.tree.insert("", tk.END, values=values)
            self.item_to_key[item] = key

        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=2)
        ttk.Label(right_frame, text="Редактирование полос", font=("Arial", 12)).pack(pady=5)

        self.edit_frame = ttk.Frame(right_frame)
        self.edit_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(self.edit_frame)
        self.scrollbar = ttk.Scrollbar(self.edit_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(side=tk.BOTTOM, pady=10)
        ttk.Button(btn_frame, text="Применить изменения", command=self.apply_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Сохранить и перестроить сеть", command=self.save_and_rebuild).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Сбросить интенсивность", command=self.reset_to_default).pack(side=tk.LEFT, padx=5)

        self.current_group_key = None
        self.clear_edit_panel()

    def clear_edit_panel(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

    def on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        key = self.item_to_key.get(item)
        if key is None:
            return
        self.current_group_key = key
        self.show_edit_panel(key)

    def show_edit_panel(self, key):
        self.clear_edit_panel()
        group = self.groups[key]

        if not group["has_in"]:
            ttk.Label(self.scrollable_frame, text="Нет въездных полос для редактирования").pack()
            return

        lanes = group["lanes_in"]
        turn_lanes = group["turn_lanes"]
        lane_flow_rates = group["lane_flow_rates"]

        while len(turn_lanes) < lanes:
            turn_lanes.append(["through"])
        turn_lanes = turn_lanes[:lanes]

        while len(lane_flow_rates) < lanes:
            lane_flow_rates.append(DEFAULT_FLOW_RATE)
        lane_flow_rates = lane_flow_rates[:lanes]

        group["turn_lanes"] = turn_lanes
        group["lane_flow_rates"] = lane_flow_rates
        if group["in_app"] is not None:
            group["in_app"]["turn_lanes"] = turn_lanes
            group["in_app"]["lane_flow_rates"] = lane_flow_rates

        direction = angle_to_direction(group["angle_deg"])
        ttk.Label(self.scrollable_frame,
                  text=f"Улица: {group['street_name']}  |  Направление: {direction}",
                  font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)

        self.lane_vars = []
        self.flow_vars = []

        for sumo_idx in range(lanes - 1, -1, -1):
            ui_num = lanes - sumo_idx
            frame = ttk.Frame(self.scrollable_frame, relief=tk.GROOVE, borderwidth=1)
            frame.pack(fill=tk.X, pady=3, padx=5)

            header_frame = ttk.Frame(frame)
            header_frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(header_frame, text=f"Полоса {ui_num}:", font=("Arial", 9, "bold"), width=10).pack(side=tk.LEFT)

            ttk.Label(header_frame, text="Интенсивность (авто/час):").pack(side=tk.LEFT, padx=(20, 5))
            flow_var = tk.StringVar(value=str(lane_flow_rates[sumo_idx] if sumo_idx < len(lane_flow_rates) else DEFAULT_FLOW_RATE))
            flow_entry = ttk.Entry(header_frame, textvariable=flow_var, width=8)
            flow_entry.pack(side=tk.LEFT, padx=5)
            self.flow_vars.append(flow_var)

            maneuvers = turn_lanes[sumo_idx] if sumo_idx < len(turn_lanes) else ["through"]
            maneuvers = [m for m in maneuvers if m in ALL_MANEUVERS]
            if not maneuvers:
                maneuvers = ["through"]

            maneuvers_frame = ttk.Frame(frame)
            maneuvers_frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(maneuvers_frame, text="Маневры:", width=10).pack(side=tk.LEFT)

            vars_row = []
            for man in ALL_MANEUVERS:
                var = tk.IntVar(value=1 if man in maneuvers else 0)
                cb = ttk.Checkbutton(maneuvers_frame, text=man, variable=var)
                cb.pack(side=tk.LEFT, padx=2)
                vars_row.append(var)
            self.lane_vars.append(vars_row)

    def apply_changes(self):
        if self.current_group_key is None:
            return
        group = self.groups[self.current_group_key]
        if not group["has_in"]:
            return

        lanes = group["lanes_in"]

        new_turn_lanes_reversed = []
        for vars_row in self.lane_vars:
            maneuvers = [ALL_MANEUVERS[i] for i, var in enumerate(vars_row) if var.get() == 1]
            if not maneuvers:
                maneuvers = ["through"]
            new_turn_lanes_reversed.append(maneuvers)

        new_turn_lanes = list(reversed(new_turn_lanes_reversed))

        new_flow_rates_reversed = []
        for flow_var in self.flow_vars:
            try:
                rate = int(flow_var.get())
                if rate < 0:
                    rate = 0
                new_flow_rates_reversed.append(rate)
            except ValueError:
                messagebox.showerror("Ошибка", "Введите целое число для интенсивности")
                return

        new_flow_rates = list(reversed(new_flow_rates_reversed))

        group["turn_lanes"] = new_turn_lanes
        group["lane_flow_rates"] = new_flow_rates
        if group["in_app"] is not None:
            group["in_app"]["turn_lanes"] = new_turn_lanes
            group["in_app"]["lane_flow_rates"] = new_flow_rates

        messagebox.showinfo("Успех",
                            f"Изменения применены к {group['street_name']}")

    def reset_to_default(self):
        """Сбрасывает все lane_flow_rates на DEFAULT_FLOW_RATE"""
        if not messagebox.askyesno("Подтверждение", "Сбросить все интенсивности на значение по умолчанию?"):
            return

        for key, group in self.groups.items():
            if group["has_in"]:
                lanes = group["lanes_in"]
                group["lane_flow_rates"] = [DEFAULT_FLOW_RATE] * lanes
                if group["in_app"] is not None:
                    group["in_app"]["lane_flow_rates"] = [DEFAULT_FLOW_RATE] * lanes

        if self.current_group_key is not None:
            self.show_edit_panel(self.current_group_key)

        messagebox.showinfo("Успех", f"Все интенсивности сброшены на {DEFAULT_FLOW_RATE}")

    def save_and_rebuild(self):
        self.apply_changes()

        new_approaches = []
        for key, group in self.groups.items():
            if group["has_in"]:
                in_app = {
                    "street_name": group["street_name"],
                    "angle_deg": group["angle_deg"],
                    "lanes": group["lanes_in"],
                    "turn_lanes": group["turn_lanes"],
                    "lane_flow_rates": group["lane_flow_rates"],
                    "traffic_lights": group["traffic_lights"],
                    "direction": "ВЪЕЗД"
                }
                new_approaches.append(in_app)
            if group["has_out"]:
                out_app = {
                    "street_name": group["street_name"],
                    "angle_deg": group["angle_deg"],
                    "lanes": group["lanes_out"],
                    "turn_lanes": [],
                    "traffic_lights": [],
                    "direction": "ВЫЕЗД"
                }
                new_approaches.append(out_app)

        try:
            with open(GEOMETRY_FILE, "w", encoding="utf-8") as f:
                json.dump(new_approaches, f, ensure_ascii=False, indent=2)
            print(f"✅ Сохранён {GEOMETRY_FILE}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить {GEOMETRY_FILE}: {e}")
            return

        try:
            print("Перестроение сети...")
            build_network(new_approaches, NET_FILE)
            print("Сеть построена.")
            generate_routes_from_network(NET_FILE, ROUTES_FILE, CONFIG_FILE, GEOMETRY_FILE)
            print("Маршруты и детекторы сгенерированы.")
            messagebox.showinfo("Готово", "Сеть успешно перестроена!\nМожно запускать sumo-gui.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось перестроить сеть:\n{e}")
            import traceback
            traceback.print_exc()


def main():
    root = tk.Tk()
    app = ApproachEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()