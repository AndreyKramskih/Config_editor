import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import copy
import os

# ---------- Шаблон по умолчанию ----------
DEFAULT_TEMPLATE = {
    "project_name": "Новый проект",
    "modbus_server": {
        "ip": "192.168.101.250", "port": 502, "slave_id": 16,
        "timeout": 3, "retries": 3
    },
    "systems": {},
    "connection": {"name": "Подключение к оборудованию", "icon": "📡"},
    "connection_type": "rtu",
    "rtu_config": {
        "port": "/dev/bus/usb/002/002", "baud_rate": 115200,
        "data_bits": 8, "stop_bits": 1, "parity": "none"
    }
}

SUBMENU_TYPES = ["sensors", "relays", "pumps", "valve", "settings", "alarms", "startstop"]

ITEM_SCHEMAS = {
    "sensors": {"title": "Датчик", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес Modbus", "int"),
        ("type", "Тип", "choice:int|float|bool|str"),
        ("unit", "Ед.изм.", "str"),
        ("min", "Мин", "float"),
        ("max", "Макс", "float"),
        ("is_setpoint", "Уставка", "bool"),
        ("icon", "Иконка", "str"),
    ]},
    "relays": {"title": "Реле", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес", "int"),
        ("bit", "Бит (0-15)", "int"),
        ("states", "Состояния (через ;)", "list"),
    ]},
    "pumps": {"title": "Насос", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес", "int"),
        ("bit", "Бит (0-15)", "int"),
        ("states", "Состояния (через ;)", "list"),
        ("mode_address", "Адрес режима", "int"),
        ("mode_states", "Режимы (через ;)", "list"),
    ]},
    "alarms": {"title": "Авария", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес", "int"),
        ("bit", "Бит (0-15)", "int"),
        ("description", "Описание", "str"),
    ]},
    "startstop": {"title": "Вкл/Выкл", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес", "int"),
        ("bit", "Бит (0-15)", "int"),
        ("states", "Состояния (через ;)", "list"),
    ]},
    "valve": {"title": "Клапан", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес", "int"),
        ("bit", "Бит (0-15)", "int"),
        ("states", "Состояния (через ;)", "list"),
    ]},
    "settings": {"title": "Параметр", "fields": [
        ("name", "Название", "str"),
        ("address", "Адрес", "int"),
        ("type", "Тип", "choice:int|float|bool|str"),
        ("unit", "Ед.изм.", "str"),
        ("min", "Мин", "float"),
        ("max", "Макс", "float"),
        ("default", "По умолчанию", "str"),
    ]},
}


def pretty_type(v):
    return {int: "int", float: "float", bool: "bool", str: "str", list: "list",
            dict: "dict", type(None): "none"}.get(type(v), str(type(v).__name__))


def coerce(value, vtype):
    if value is None:
        return None
    s = str(value).strip()
    try:
        if vtype is int:
            return int(float(s)) if s else 0
        if vtype is float:
            return float(s) if s else 0.0
        if vtype is bool:
            return s.lower() in ("1", "true", "да", "yes", "on")
        if vtype is list:
            return [x.strip() for x in s.split(";") if x.strip()]
        return s
    except ValueError:
        raise ValueError(f"Неверное значение: {value!r}")


def parse_by_field_type(text, ftype):
    if ftype == "int":
        return int(float(text)) if str(text).strip() else 0
    if ftype == "float":
        return float(text) if str(text).strip() else 0.0
    if ftype == "bool":
        return str(text).strip().lower() in ("1", "true", "да", "yes", "on")
    if ftype == "list":
        return [x.strip() for x in str(text).split(";") if x.strip()]
    if ftype.startswith("choice:"):
        choices = ftype.split(":", 1)[1].split("|")
        if text not in choices:
            raise ValueError(f"Нужно одно из: {choices}")
        if text == "int":
            return 0
        if text == "float":
            return 0.0
        if text == "bool":
            return False
        return text
    return str(text)


class ConfigEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Редактор конфигураций ЮГ")
        self.geometry("1280x780")
        self.data = copy.deepcopy(DEFAULT_TEMPLATE)
        self.current_file = None
        self._node_map = {}
        self.clipboard = None
        self._path_to_item = {}
        self._item_to_path = {}
        self._search_index = []
        self._search_matches = []
        self._search_pos = -1

        self._build_ui()
        self._refresh_tree()

        self.bind_all("<Control-c>", lambda e: self._copy_selected())
        self.bind_all("<Control-v>", lambda e: self._paste_to_selected())
        self.bind_all("<Control-d>", lambda e: self._duplicate_selected())
        self.bind_all("<Delete>",    lambda e: self._delete_from_selection())
        self.bind_all("<Control-f>", lambda e: self.search_entry.focus_set())

    # ================= UI =================
    def _build_ui(self):
        tb = ttk.Frame(self)
        tb.pack(fill="x", padx=5, pady=5)
        ttk.Button(tb, text="📂 Открыть шаблон", command=self.load_file).pack(side="left")
        ttk.Button(tb, text="💾 Сохранить как…", command=self.save_file_as).pack(side="left", padx=5)
        ttk.Button(tb, text="🆕 Новый (пустой)", command=self.new_blank).pack(side="left", padx=5)
        ttk.Button(tb, text="🔍 Проверить адреса", command=self.check_address_conflicts)\
            .pack(side="left", padx=5)
        self.path_label = ttk.Label(tb, text="—", foreground="gray")
        self.path_label.pack(side="right")

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        # ---- Левая часть: поиск + дерево ----
        left = ttk.Frame(paned)
        ttk.Label(left, text="Структура проекта", font=("Segoe UI", 10, "bold")).pack(anchor="w")

        search_frame = ttk.Frame(left)
        search_frame.pack(fill="x", pady=(4, 4))
        ttk.Label(search_frame, text="🔎").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self.search_entry.bind("<Return>", lambda e: self._search_next())
        self.search_entry.bind("<KeyRelease>", self._on_search_key)
        self.search_entry.bind("<Escape>", lambda e: self._clear_search())
        ttk.Button(search_frame, text="◀", width=3,
                   command=lambda: self._search_next(-1)).pack(side="left")
        ttk.Button(search_frame, text="▶", width=3,
                   command=lambda: self._search_next(+1)).pack(side="left")

        self.search_results = tk.Listbox(left, height=6, exportselection=False)
        self.search_results.bind("<<ListboxSelect>>", self._on_search_result_pick)
        self.search_results.bind("<Return>", lambda e: self._on_search_result_pick(None))
        self.search_results.bind("<Double-Button-1>", lambda e: self._on_search_result_pick(None))

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-3>", self._show_tree_menu)
        paned.add(left, weight=1)

        # ---- Правая часть: форма ----
        right = ttk.Frame(paned)
        self.form_holder = ttk.Frame(right)
        self.form_holder.pack(fill="both", expand=True)
        paned.add(right, weight=3)

        # ---- Контекстное меню ----
        self._tree_menu = tk.Menu(self, tearoff=0)
        self._tree_menu.add_command(label="📋 Копировать", command=self._copy_selected)
        self._tree_menu.add_command(label="📋 Вставить", command=self._paste_to_selected)
        self._tree_menu.add_command(label="📋 Вставить со сдвигом…", command=self._paste_with_offset)
        self._tree_menu.add_command(label="📄 Дублировать", command=self._duplicate_selected)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="📂 Развернуть всё", command=self._expand_all)
        self._tree_menu.add_command(label="📁 Свернуть всё", command=self._collapse_all)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="🗑 Удалить", command=self._delete_from_selection)

    def _show_tree_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
        self._tree_menu.tk_popup(event.x_root, event.y_root)

    # ================= Дерево =================
    def _refresh_tree(self, select_path=None):
        state = self._capture_tree_state()
        self.tree.delete(*self.tree.get_children())
        self._node_map.clear()
        self._path_to_item.clear()
        self._item_to_path.clear()

        root = self.tree.insert("", "end", text="📦 проект", open=True)
        self._node_map[root] = (self.data, None)
        self._set_item_path(root, ())
        self._build_children(root, self.data, ())

        if select_path is not None:
            self._select_by_json_path(select_path)
        else:
            self._restore_tree_state(state)

        self._rebuild_search_index()

    def _set_item_path(self, item, path):
        self._item_to_path[item] = path
        self._path_to_item[path] = item

    def _capture_tree_state(self):
        open_paths = set()
        for item in self._iter_items():
            if self.tree.item(item, "open"):
                p = self._item_to_path.get(item)
                if p is not None:
                    open_paths.add(p)
        selection_paths = []
        for item in self.tree.selection():
            p = self._item_to_path.get(item)
            if p is not None:
                selection_paths.append(p)
        try:
            top = self.tree.yview()[0]
        except Exception:
            top = 0.0
        return {"open": open_paths, "selection": selection_paths, "top": top}

    def _restore_tree_state(self, state):
        for p in state["open"]:
            it = self._path_to_item.get(p)
            if it:
                try:
                    self.tree.item(it, open=True)
                except Exception:
                    pass
        sel_items = [self._path_to_item[p] for p in state["selection"]
                     if p in self._path_to_item]
        if sel_items:
            self.tree.selection_set(sel_items)
            self.tree.focus(sel_items[-1])
            self.tree.see(sel_items[-1])
        try:
            self.tree.yview_moveto(state["top"])
        except Exception:
            pass

    def _iter_items(self, parent=""):
        for ch in self.tree.get_children(parent):
            yield ch
            yield from self._iter_items(ch)

    def _select_by_json_path(self, path):
        it = self._path_to_item.get(tuple(path))
        if it:
            cur = self.tree.parent(it)
            while cur:
                self.tree.item(cur, open=True)
                cur = self.tree.parent(cur)
            self.tree.selection_set(it)
            self.tree.focus(it)
            self.tree.see(it)

    def _build_children(self, parent, obj, base_path=()):
        if not isinstance(obj, dict):
            return
        for k, v in obj.items():
            cur_path = base_path + (k,)
            if k == "systems" and isinstance(v, dict):
                node = self.tree.insert(parent, "end", text="🔧 systems", open=True)
                self._node_map[node] = (obj, k)
                self._set_item_path(node, cur_path)
                for sys_key, sys_val in v.items():
                    sys_path = cur_path + (sys_key,)
                    icon = sys_val.get("icon", "⚙") if isinstance(sys_val, dict) else "⚙"
                    sname = sys_val.get("name", sys_key) if isinstance(sys_val, dict) else sys_key
                    s = self.tree.insert(node, "end", text=f"{icon} {sname} [{sys_key}]", open=True)
                    self._node_map[s] = (v, sys_key)
                    self._set_item_path(s, sys_path)
                    if isinstance(sys_val, dict) and "submenus" in sys_val:
                        subs = sys_val["submenus"]
                        subs_node = self.tree.insert(s, "end", text="📂 submenus", open=True)
                        self._node_map[subs_node] = (sys_val, "submenus")
                        self._set_item_path(subs_node, sys_path + ("submenus",))
                        for sub_key, sub_val in subs.items():
                            sub_path = sys_path + ("submenus", sub_key)
                            icon2 = sub_val.get("icon", "📄") if isinstance(sub_val, dict) else "📄"
                            sname2 = sub_val.get("name", sub_key) if isinstance(sub_val, dict) else sub_key
                            sub_node = self.tree.insert(subs_node, "end",
                                                        text=f"{icon2} {sname2} [{sub_key}]", open=True)
                            self._node_map[sub_node] = (subs, sub_key)
                            self._set_item_path(sub_node, sub_path)
                            self._build_submenu_children(sub_node, sub_val, sub_path)
            elif isinstance(v, dict):
                node = self.tree.insert(parent, "end", text=f"📁 {k}", open=False)
                self._node_map[node] = (obj, k)
                self._set_item_path(node, cur_path)
                self._build_children(node, v, cur_path)
            elif isinstance(v, list):
                node = self.tree.insert(parent, "end", text=f"📃 {k} [{len(v)}]", open=False)
                self._node_map[node] = (obj, k)
                self._set_item_path(node, cur_path)
                for i, item in enumerate(v):
                    iname = item.get("name", f"[{i}]") if isinstance(item, dict) else str(item)
                    n = self.tree.insert(node, "end", text=f"{i}: {iname}")
                    self._node_map[n] = (v, i)
                    self._set_item_path(n, cur_path + (i,))

    def _build_submenu_children(self, parent_node, submenu, base_path=()):
        if not isinstance(submenu, dict):
            return
        for k, v in submenu.items():
            cur_path = base_path + (k,)
            if k in ("items", "alarms", "controls", "groups") and isinstance(v, list):
                node = self.tree.insert(parent_node, "end", text=f"📃 {k} [{len(v)}]", open=True)
                self._node_map[node] = (submenu, k)
                self._set_item_path(node, cur_path)
                for i, item in enumerate(v):
                    iname = item.get("name", f"[{i}]") if isinstance(item, dict) else str(item)
                    n = self.tree.insert(node, "end", text=f"{i}: {iname}")
                    self._node_map[n] = (v, i)
                    self._set_item_path(n, cur_path + (i,))
            elif isinstance(v, dict):
                node = self.tree.insert(parent_node, "end", text=f"📁 {k}", open=False)
                self._node_map[node] = (submenu, k)
                self._set_item_path(node, cur_path)

    def on_tree_select(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        parent_obj, key = self._node_map.get(sel[0], (None, None))
        self._render_form(parent_obj, key)

    # ================= Поиск =================
    def _rebuild_search_index(self):
        self._search_index = []
        for item in self._iter_items():
            path = self._item_to_path.get(item, ())
            label = self.tree.item(item, "text")
            searchable = (label + " " + "/".join(str(p) for p in path)).lower()
            self._search_index.append((item, label, path, searchable))
        self._search_matches = []
        self._search_pos = -1

    def _on_search_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        q = self.search_var.get().strip().lower()
        self.search_results.delete(0, "end")
        if not q:
            self.search_results.pack_forget()
            self._search_matches = []
            return
        hits = [t for t in self._search_index if q in t[3]]
        self._search_matches = [t[0] for t in hits[:50]]
        for item, label, path, _ in hits[:50]:
            self.search_results.insert("end", label)
        if hits:
            self.search_results.pack(fill="x", pady=(0, 4))
        else:
            self.search_results.pack_forget()

    def _search_next(self, direction=+1):
        if not self._search_matches:
            q = self.search_var.get().strip().lower()
            if not q:
                return
            self._search_matches = [t[0] for t in self._search_index if q in t[3]]
            if not self._search_matches:
                return
            self._search_pos = -1
        self._search_pos = (self._search_pos + direction) % len(self._search_matches)
        self._go_to_item(self._search_matches[self._search_pos])

    def _on_search_result_pick(self, _):
        sel = self.search_results.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._search_matches):
            self._go_to_item(self._search_matches[idx])
            self.search_results.pack_forget()

    def _go_to_item(self, item):
        cur = self.tree.parent(item)
        while cur:
            self.tree.item(cur, open=True)
            cur = self.tree.parent(cur)
        self.tree.selection_set(item)
        self.tree.focus(item)
        self.tree.see(item)

    def _clear_search(self):
        self.search_var.set("")
        self.search_results.delete(0, "end")
        self.search_results.pack_forget()
        self._search_matches = []

    def _expand_all(self):
        for item in self._iter_items():
            self.tree.item(item, open=True)

    def _collapse_all(self):
        for item in self._iter_items():
            if self.tree.parent(item):
                self.tree.item(item, open=False)

    # ================= Форма =================
    def _render_form(self, parent_obj, key):
        for w in self.form_holder.winfo_children():
            w.destroy()

        if parent_obj is None and key is None:
            self._render_root_form()
            return

        obj = parent_obj[key]

        btn_bar = ttk.Frame(self.form_holder)
        btn_bar.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_bar, text="➕ Добавить",
                   command=lambda: self._add_dialog(parent_obj, key)).pack(side="left")
        ttk.Button(btn_bar, text="🗑 Удалить",
                   command=lambda: self._delete_current(parent_obj, key)).pack(side="left", padx=5)

        canvas = tk.Canvas(self.form_holder, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(self.form_holder, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._build_form_widgets(inner, parent_obj, key, obj)

    def _render_root_form(self):
        f = ttk.LabelFrame(self.form_holder, text="Проект")
        f.pack(fill="x", padx=5, pady=5)
        self._scalar_fields(f, self.data, ["project_name"], skip_lists=True)

        f2 = ttk.LabelFrame(self.form_holder, text="modbus_server")
        f2.pack(fill="x", padx=5, pady=5)
        self._scalar_fields(f2, self.data["modbus_server"], list(self.data["modbus_server"].keys()))

        f3 = ttk.LabelFrame(self.form_holder, text="connection / rtu_config")
        f3.pack(fill="x", padx=5, pady=5)
        self._scalar_fields(f3, self.data["connection"], ["name", "icon"])
        self._scalar_fields(f3, self.data["rtu_config"], list(self.data["rtu_config"].keys()))

        ttk.Button(self.form_holder, text="Применить изменения в структуре",
                   command=self._refresh_tree).pack(pady=10)

    def _scalar_fields(self, parent, obj, keys, skip_lists=False):
        r = 0
        for k in keys:
            if k not in obj:
                continue
            v = obj[k]
            if skip_lists and isinstance(v, (dict, list)):
                continue
            ttk.Label(parent, text=k + ":").grid(row=r, column=0, sticky="w", padx=5, pady=2)
            var = tk.StringVar(value="" if v is None else str(v))
            e = ttk.Entry(parent, textvariable=var, width=45)
            e.grid(row=r, column=1, sticky="ew", padx=5, pady=2)

            def make_upd(o=obj, kk=k, vv=v, va=var):
                def upd(_=None):
                    try:
                        o[kk] = coerce(va.get(), type(vv))
                    except ValueError as ex:
                        messagebox.showerror("Ошибка", f"{kk}: {ex}")
                return upd

            e.bind("<FocusOut>", make_upd())
            e.bind("<Return>", make_upd())
            r += 1
        parent.columnconfigure(1, weight=1)

    def _build_form_widgets(self, parent, parent_obj, key, obj):
        title = key if not isinstance(key, int) else f"Элемент [{key}]"
        ttk.Label(parent, text=f"Редактирование: {title}",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2,
                                                      sticky="w", padx=5, pady=(0, 8))
        if isinstance(obj, dict):
            r = 1
            for k, v in obj.items():
                ttk.Label(parent, text=k).grid(row=r, column=0, sticky="nw", padx=5, pady=2)
                if isinstance(v, (dict, list)):
                    ttk.Label(parent, text=f"<{pretty_type(v)}> (редактируется в дереве)",
                              foreground="gray").grid(row=r, column=1, sticky="w", padx=5, pady=2)
                else:
                    if isinstance(v, bool):
                        var = tk.BooleanVar(value=v)
                        w = ttk.Checkbutton(parent, variable=var)
                        w.grid(row=r, column=1, sticky="w", padx=5, pady=2)

                        def make_upd_bool(o=obj, kk=k, va=var):
                            def upd(*_):
                                o[kk] = bool(va.get())
                            return upd
                        var.trace_add("write", lambda *a, u=make_upd_bool(): u())
                    else:
                        var = tk.StringVar(value="" if v is None else str(v))
                        w = ttk.Entry(parent, textvariable=var, width=45)
                        w.grid(row=r, column=1, sticky="ew", padx=5, pady=2)

                        def make_upd(o=obj, kk=k, vv=v, va=var):
                            def upd(_=None):
                                try:
                                    o[kk] = coerce(va.get(), type(vv))
                                except ValueError as ex:
                                    messagebox.showerror("Ошибка", f"{kk}: {ex}")
                            return upd
                        w.bind("<FocusOut>", make_upd())
                        w.bind("<Return>", make_upd())
                r += 1
            parent.columnconfigure(1, weight=1)
        elif isinstance(obj, list):
            ttk.Label(parent, text=f"Список из {len(obj)} элементов.",
                      foreground="gray").grid(row=1, column=0, columnspan=2, sticky="w", padx=5)
        else:
            ttk.Label(parent, text=repr(obj)).grid(row=1, column=0, sticky="w", padx=5)

        ttk.Button(parent, text="🔄 Обновить дерево", command=self._refresh_tree)\
            .grid(row=99, column=0, columnspan=2, sticky="w", padx=5, pady=10)

    # ================= Добавление =================
    def _add_dialog(self, parent_obj, key):
        obj = parent_obj[key] if not isinstance(parent_obj, list) else parent_obj[key]

        if isinstance(obj, dict) and "systems" in obj and key == "systems":
            self._add_system_dialog(obj["systems"])
        elif isinstance(key, str) and key == "systems":
            self._add_system_dialog(obj)
        elif isinstance(key, str) and key == "submenus":
            self._add_submenu_dialog(obj)
        elif isinstance(key, str) and key in ITEM_SCHEMAS:
            self._add_submenu_item(obj, key)
        elif isinstance(obj, list):
            self._add_item_to_list(obj, key)
        else:
            messagebox.showinfo("Добавление", "Для этого узла добавление не предусмотрено.")

    def _add_system_dialog(self, systems):
        dlg = tk.Toplevel(self)
        dlg.title("Новая система")
        dlg.geometry("420x220")
        dlg.transient(self); dlg.grab_set()

        ttk.Label(dlg, text="Ключ (латиницей):").pack(anchor="w", padx=10, pady=(10, 0))
        key_var = tk.StringVar(); ttk.Entry(dlg, textvariable=key_var, width=40).pack(padx=10, pady=2)
        ttk.Label(dlg, text="Название:").pack(anchor="w", padx=10, pady=(8, 0))
        name_var = tk.StringVar(); ttk.Entry(dlg, textvariable=name_var, width=40).pack(padx=10, pady=2)
        ttk.Label(dlg, text="Иконка:").pack(anchor="w", padx=10, pady=(8, 0))
        icon_var = tk.StringVar(value="⚙️"); ttk.Entry(dlg, textvariable=icon_var, width=10).pack(anchor="w", padx=10, pady=2)

        def ok():
            k = key_var.get().strip()
            if not k or not k.replace("_", "").isalnum():
                messagebox.showerror("Ошибка", "Ключ: латиница/цифры/_"); return
            if k in systems:
                messagebox.showerror("Ошибка", "Такая система уже есть"); return
            systems[k] = {"name": name_var.get().strip() or k,
                          "icon": icon_var.get().strip(), "submenus": {}}
            dlg.destroy(); self._refresh_tree(select_path=("systems", k))
        ttk.Button(dlg, text="Создать", command=ok).pack(pady=10)

    def _add_submenu_dialog(self, submenus):
        dlg = tk.Toplevel(self)
        dlg.title("Новое подменю"); dlg.geometry("420x260")
        dlg.transient(self); dlg.grab_set()

        ttk.Label(dlg, text="Ключ:").pack(anchor="w", padx=10, pady=(10, 0))
        key_var = tk.StringVar(); ttk.Entry(dlg, textvariable=key_var, width=40).pack(padx=10, pady=2)
        ttk.Label(dlg, text="Название:").pack(anchor="w", padx=10, pady=(8, 0))
        name_var = tk.StringVar(); ttk.Entry(dlg, textvariable=name_var, width=40).pack(padx=10, pady=2)
        ttk.Label(dlg, text="Иконка:").pack(anchor="w", padx=10, pady=(8, 0))
        icon_var = tk.StringVar(value="📄"); ttk.Entry(dlg, textvariable=icon_var, width=10).pack(anchor="w", padx=10, pady=2)
        ttk.Label(dlg, text="Тип:").pack(anchor="w", padx=10, pady=(8, 0))
        type_var = tk.StringVar(value="sensors")
        ttk.Combobox(dlg, textvariable=type_var, values=SUBMENU_TYPES,
                     state="readonly").pack(anchor="w", padx=10, pady=2)

        def ok():
            k = key_var.get().strip()
            if not k or not k.replace("_", "").isalnum():
                messagebox.showerror("Ошибка", "Ключ: латиница/цифры/_"); return
            if k in submenus:
                messagebox.showerror("Ошибка", "Такое подменю уже есть"); return
            t = type_var.get()
            new = {"name": name_var.get().strip() or k,
                   "icon": icon_var.get().strip(), "type": t}
            if t == "alarms":
                new["alarms"] = []; new["reset_address"] = 513; new["reset_bit"] = 1
            elif t == "settings":
                new["groups"] = []
            elif t == "valve":
                new["items"] = []; new["controls"] = []
            else:
                new["items"] = []
            submenus[k] = new
            dlg.destroy(); self._refresh_tree()
        ttk.Button(dlg, text="Создать", command=ok).pack(pady=10)

    def _add_submenu_item(self, submenu, submenu_key):
        if submenu_key == "alarms":
            key_list, schema = "alarms", ITEM_SCHEMAS["alarms"]
        elif submenu_key == "settings":
            groups = submenu.get("groups", [])
            if not groups:
                messagebox.showerror("Ошибка", "Сначала создайте группу."); return
            groups[0].setdefault("items", []).append({})
            self._refresh_tree(); return
        elif submenu_key == "valve":
            key_list, schema = "items", ITEM_SCHEMAS["valve"]
        elif submenu_key == "startstop":
            key_list, schema = "items", ITEM_SCHEMAS["startstop"]
        elif submenu_key == "pumps":
            key_list, schema = "items", ITEM_SCHEMAS["pumps"]
        elif submenu_key == "relays":
            key_list, schema = "items", ITEM_SCHEMAS["relays"]
        elif submenu_key == "sensors":
            key_list, schema = "items", ITEM_SCHEMAS["sensors"]
        else:
            return
        target = submenu.setdefault(key_list, [])
        new_item = self._prompt_item(schema)
        if new_item is not None:
            target.append(new_item); self._refresh_tree()

    def _add_item_to_list(self, lst, key):
        if key == "alarms":
            schema = ITEM_SCHEMAS["alarms"]
        elif key == "items":
            schema = ITEM_SCHEMAS["sensors"]
        elif key == "controls":
            schema = {"title": "Управление", "fields": [
                ("name", "Название", "str"), ("address", "Адрес", "int"),
                ("value", "Значение", "int"),
                ("type", "Тип", "choice:int|float|bool|str")]}
        elif key == "groups":
            schema = {"title": "Группа настроек", "fields": [("name", "Название", "str")]}
        else:
            schema = ITEM_SCHEMAS["sensors"]
        new_item = self._prompt_item(schema)
        if new_item is not None:
            lst.append(new_item); self._refresh_tree()

    def _prompt_item(self, schema):
        dlg = tk.Toplevel(self)
        dlg.title(f"Добавить: {schema['title']}")
        dlg.transient(self); dlg.grab_set()
        vars_ = {}
        r = 0
        for fname, flabel, ftype in schema["fields"]:
            ttk.Label(dlg, text=flabel).grid(row=r, column=0, sticky="w", padx=10, pady=3)
            if ftype.startswith("choice:"):
                choices = ftype.split(":", 1)[1].split("|")
                v = tk.StringVar(value=choices[0])
                w = ttk.Combobox(dlg, textvariable=v, values=choices, state="readonly", width=30)
            elif ftype == "bool":
                v = tk.BooleanVar(value=False)
                w = ttk.Checkbutton(dlg, variable=v)
            else:
                v = tk.StringVar()
                w = ttk.Entry(dlg, textvariable=v, width=32)
            w.grid(row=r, column=1, sticky="ew", padx=10, pady=3)
            vars_[fname] = (v, ftype); r += 1

        def ok():
            result = {}
            try:
                for fname, (v, ftype) in vars_.items():
                    val = v.get()
                    result[fname] = bool(val) if ftype == "bool" else parse_by_field_type(val, ftype)
            except Exception as ex:
                messagebox.showerror("Ошибка", str(ex)); return
            dlg.result = result; dlg.destroy()

        ttk.Button(dlg, text="OK", command=ok).grid(row=r, column=0, columnspan=2, pady=10)
        dlg.result = None
        self.wait_window(dlg)
        return getattr(dlg, "result", None)

    # ================= Удаление =================
    def _delete_current(self, parent_obj, key):
        if parent_obj is None and key is None:
            return
        if isinstance(parent_obj, dict):
            if isinstance(key, int):
                return
            if not messagebox.askyesno("Удаление", f"Удалить «{key}»?"):
                return
            del parent_obj[key]
        elif isinstance(parent_obj, list):
            if not messagebox.askyesno("Удаление", f"Удалить элемент [{key}]?"):
                return
            parent_obj.pop(key)
        self._refresh_tree()

    # ================= Копирование / вставка / дублирование =================
    def _selection_info(self):
        sel = self.tree.selection()
        if not sel:
            return None, None, None
        parent_obj, key = self._node_map.get(sel[0], (None, None))
        return parent_obj, key, self._classify(parent_obj, key)

    def _classify(self, parent_obj, key):
        if parent_obj is None and key is None:
            return "root"
        if isinstance(parent_obj, dict):
            if key == "systems":
                return "systems_folder"
            if key == "submenus":
                return "submenus_folder"
            if key in SUBMENU_TYPES:
                return "submenu"
            if key in ("items", "alarms", "controls", "groups"):
                return "list_folder"
            return "other_dict"
        if isinstance(parent_obj, list):
            return "item"
        return "other"

    def _copy_selected(self, silent=False):
        parent_obj, key, kind = self._selection_info()
        if parent_obj is None and key is None:
            if not silent:
                messagebox.showinfo("Копирование", "Нечего копировать")
            return False
        if isinstance(parent_obj, dict) and key in ("systems", "submenus"):
            if not silent:
                messagebox.showinfo("Копирование", "Выберите конкретный элемент, а не папку.")
            return False

        obj = parent_obj[key]
        payload = copy.deepcopy(obj)

        if isinstance(parent_obj, dict) and isinstance(obj, dict) and "submenus" in obj and "name" in obj:
            self.clipboard = {"kind": "system", "payload": payload, "src_key": key}
        elif isinstance(parent_obj, dict) and isinstance(obj, dict) and "type" in obj:
            self.clipboard = {"kind": "submenu", "payload": payload, "src_key": key}
        elif isinstance(parent_obj, dict) and isinstance(obj, dict) and "groups" in obj:
            self.clipboard = {"kind": "settings_group", "payload": payload, "src_key": key}
        elif isinstance(parent_obj, list):
            self.clipboard = {"kind": "item", "payload": payload, "src_key": None}
        elif isinstance(parent_obj, dict):
            self.clipboard = {"kind": "dict_value", "payload": payload, "src_key": key}
        else:
            self.clipboard = {"kind": "scalar", "payload": payload, "src_key": None}

        if not silent:
            messagebox.showinfo("Копирование",
                                f"Скопировано: {self.clipboard['kind']} "
                                f"({key if key is not None else 'элемент'})")
        return True

    def _paste_to_selected(self):
        if not self.clipboard:
            messagebox.showinfo("Вставка", "Буфер пуст")
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Вставка", "Выберите куда вставить")
            return

        parent_obj, key = self._node_map.get(sel[0], (None, None))
        obj = parent_obj[key] if parent_obj is not None else self.data
        kind = self.clipboard["kind"]
        payload = copy.deepcopy(self.clipboard["payload"])

        try:
            if kind == "system":
                self._paste_system(obj, parent_obj, key, payload)
            elif kind == "submenu":
                self._paste_submenu(obj, parent_obj, key, payload)
            elif kind == "settings_group":
                self._paste_group(obj, parent_obj, key, payload)
            elif kind == "item":
                self._paste_item(obj, parent_obj, key, payload)
            else:
                messagebox.showinfo("Вставка", "Этот тип не поддерживает вставку.")
                return
        except Exception as ex:
            messagebox.showerror("Вставка", f"Не удалось вставить: {ex}")
            return
        self._refresh_tree()

    def _duplicate_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        parent_obj, key = self._node_map.get(sel[0], (None, None))
        if parent_obj is None and key is None:
            messagebox.showinfo("Дублировать", "Выберите конкретный узел.")
            return
        if isinstance(parent_obj, dict) and key in ("systems", "submenus"):
            messagebox.showinfo("Дублировать", "Выберите конкретный элемент, а не папку.")
            return

        if not self._copy_selected(silent=True):
            return
        payload = copy.deepcopy(self.clipboard["payload"])

        if isinstance(parent_obj, list) and isinstance(payload, dict) and "name" in payload:
            payload["name"] = payload["name"] + " (копия)"

        try:
            if isinstance(parent_obj, list):
                parent_obj.append(payload)
            elif isinstance(parent_obj, dict):
                base = self.clipboard["src_key"] or "copy"
                new_key = self._ask_key(parent_obj, base)
                if not new_key:
                    return
                parent_obj[new_key] = payload
            else:
                messagebox.showinfo("Дублировать", "Этот узел нельзя дублировать.")
                return
        except Exception as ex:
            messagebox.showerror("Дублировать", f"Ошибка: {ex}")
            return
        self._refresh_tree()
        messagebox.showinfo("Готово", "Дубликат создан.")

    def _delete_from_selection(self):
        parent_obj, key, kind = self._selection_info()
        if parent_obj is None and key is None:
            return
        self._delete_current(parent_obj, key)

    def _ask_key(self, container, base):
        key = base
        if key in container:
            i = 2
            while f"{base}_{i}" in container:
                i += 1
            key = simpledialog.askstring("Ключ уже есть",
                                         f"Ключ «{base}» занят. Введите новый:",
                                         initialvalue=f"{base}_{i}", parent=self)
            if not key:
                return None
            key = key.strip()
            if not key or not key.replace("_", "").isalnum():
                messagebox.showerror("Ошибка", "Ключ: латиница/цифры/_")
                return None
            if key in container:
                messagebox.showerror("Ошибка", "Такой ключ тоже занят")
                return None
        return key

    def _paste_system(self, obj, parent_obj, key, payload):
        systems = None
        if parent_obj is None and key is None:
            systems = self.data.setdefault("systems", {})
        elif isinstance(parent_obj, dict) and key == "systems":
            systems = obj
        elif isinstance(obj, dict) and "systems" in obj:
            systems = obj["systems"]
        else:
            messagebox.showinfo("Вставка системы", "Выберите папку «systems» или корень проекта.")
            return
        new_key = self._ask_key(systems, payload.get("name", "system").lower()
                                .replace(" ", "_") or "system")
        if not new_key:
            return
        systems[new_key] = payload
        messagebox.showinfo("Готово", f"Система вставлена как «{new_key}»")

    def _paste_submenu(self, obj, parent_obj, key, payload):
        target_system = None
        if isinstance(obj, dict) and "submenus" in obj:
            target_system = obj
        elif isinstance(parent_obj, dict) and key == "submenus":
            target_system = {"submenus": obj}
        else:
            messagebox.showinfo("Вставка подменю", "Выберите систему или папку «submenus».")
            return
        subs = target_system.setdefault("submenus", {})
        base = payload.get("type", "submenu") or "submenu"
        new_key = self._ask_key(subs, base)
        if not new_key:
            return
        subs[new_key] = payload
        messagebox.showinfo("Готово", f"Подменю вставлено как «{new_key}»")

    def _paste_group(self, obj, parent_obj, key, payload):
        groups = None
        if isinstance(obj, dict) and "groups" in obj:
            groups = obj["groups"]
        elif isinstance(parent_obj, dict) and key == "groups":
            groups = parent_obj
        else:
            messagebox.showinfo("Вставка", "Выберите подменю «settings» или папку «groups».")
            return
        groups.append(payload)
        messagebox.showinfo("Готово", "Группа настроек вставлена")

    def _paste_item(self, obj, parent_obj, key, payload):
        if isinstance(parent_obj, dict) and key in ("items", "alarms", "controls", "groups"):
            obj.append(payload)
        elif isinstance(obj, dict):
            stype = obj.get("type", "")
            if stype == "alarms":
                obj.setdefault("alarms", []).append(payload)
            elif stype == "settings":
                groups = obj.setdefault("groups", [])
                if not groups:
                    messagebox.showerror("Вставка", "В подменю settings нет групп"); return
                groups[0].setdefault("items", []).append(payload)
            else:
                obj.setdefault("items", []).append(payload)
        else:
            messagebox.showinfo("Вставка", "Выберите подменю или папку items/alarms.")
            return
        messagebox.showinfo("Готово", "Элемент вставлен")

    def _paste_with_offset(self):
        if not self.clipboard or self.clipboard["kind"] not in ("submenu", "system"):
            messagebox.showinfo("Сдвиг", "Сначала скопируйте подменю или систему")
            return
        offset = simpledialog.askinteger("Сдвиг адресов",
                                         "Сдвинуть все address на:",
                                         initialvalue=20, minvalue=-1000, maxvalue=1000,
                                         parent=self)
        if offset is None:
            return
        payload = copy.deepcopy(self.clipboard["payload"])

        def shift(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ("address", "reset_address", "mode_address") and isinstance(v, int):
                        o[k] = v + offset
                    else:
                        shift(v)
            elif isinstance(o, list):
                for x in o:
                    shift(x)
        shift(payload)

        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Вставка", "Выберите куда вставить")
            return
        parent_obj, key = self._node_map.get(sel[0], (None, None))
        obj = parent_obj[key] if parent_obj is not None else self.data
        try:
            if self.clipboard["kind"] == "system":
                self._paste_system(obj, parent_obj, key, payload)
            else:
                self._paste_submenu(obj, parent_obj, key, payload)
        except Exception as ex:
            messagebox.showerror("Вставка", str(ex)); return
        self._refresh_tree()

    # ================= Проверка адресов =================
    def check_address_conflicts(self):
        used = {}

        def walk(o, path):
            if isinstance(o, dict):
                addr = o.get("address")
                bit = o.get("bit")
                if isinstance(addr, int) and "name" in o:
                    key = (addr, bit if isinstance(bit, int) else None)
                    used.setdefault(key, []).append(f"{path} / {o.get('name')}")
                for k, v in o.items():
                    walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{path}[{i}]")

        walk(self.data, "")
        conflicts = {k: v for k, v in used.items() if len(v) > 1}
        if not conflicts:
            messagebox.showinfo("Проверка адресов", "Конфликтов не найдено ✅")
            return
        lines = ["Найдены конфликты адресов Modbus:", ""]
        for (addr, bit), paths in sorted(conflicts.items()):
            lines.append(f"Адрес {addr}" + (f" бит {bit}" if bit is not None else "") + ":")
            for p in paths:
                lines.append("   " + p)
            lines.append("")
        messagebox.showwarning("Конфликты адресов", "\n".join(lines))

    # ================= Файл =================
    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
            self.current_file = path
            self.path_label.config(text=os.path.basename(path))
            self._refresh_tree()
        except Exception as ex:
            messagebox.showerror("Ошибка", f"Не удалось загрузить: {ex}")

    def save_file_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=os.path.basename(self.current_file) if self.current_file else "config.json",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            self.current_file = path
            self.path_label.config(text=os.path.basename(path))
            messagebox.showinfo("Готово", f"Сохранено:\n{path}")
        except Exception as ex:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {ex}")

    def new_blank(self):
        if messagebox.askyesno("Новый файл", "Создать пустой шаблон?"):
            self.data = copy.deepcopy(DEFAULT_TEMPLATE)
            self.current_file = None
            self.path_label.config(text="—")
            self._refresh_tree()


if __name__ == "__main__":
    app = ConfigEditor()
    app.mainloop()