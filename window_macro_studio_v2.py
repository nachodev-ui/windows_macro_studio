from __future__ import annotations

import json
import time
import tkinter as tk
import winsound
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from pynput import keyboard, mouse

from window_macro_recorder_v4 import PresetStore, TargetWindow, WindowMacroRecorder


EVENT_LABELS = {
    "mouse_move": "movimiento del ratón",
    "mouse_click": "clic del ratón",
    "mouse_scroll": "rueda del ratón",
    "key_press": "tecla presionada",
    "key_release": "tecla liberada",
}


class MacroStudio(tk.Tk):
    BG = "#0f172a"
    PANEL = "#111c31"
    PANEL_ALT = "#17233b"
    TEXT = "#e5edf8"
    MUTED = "#93a4bb"
    ACCENT = "#38bdf8"
    ACCENT_DARK = "#0284c7"
    DANGER = "#ef4444"
    WARNING = "#f59e0b"
    SUCCESS = "#22c55e"
    ARM_TIMEOUT_SECONDS = 15.0
    COUNTDOWN_SECONDS = 3

    def __init__(self) -> None:
        super().__init__()
        self.title("Window Macro Studio 2")
        self.geometry("1040x700")
        self.minsize(900, 620)
        self.configure(bg=self.BG)

        self.base_dir = Path(__file__).resolve().parent
        self.store = PresetStore(self.base_dir / "macros")
        self.recorder: WindowMacroRecorder | None = None
        self._closing = False
        self.recording_armed = False
        self.recording_deadline = 0.0
        self.countdown_remaining: int | None = None
        self.next_countdown_tick = 0.0
        self._last_recording = False
        self._last_replaying = False
        self._last_status_message = ""
        self._last_event_count = -1

        self.exe_var = tk.StringVar(value="Albion-Online.exe")
        self.title_var = tk.StringVar()
        self.speed_var = tk.DoubleVar(value=1.0)
        self.status_var = tk.StringVar(value="Desconectado")
        self.detail_var = tk.StringVar(value="Abre la aplicación objetivo y pulsa Conectar.")
        self.active_var = tk.StringVar(value="Ninguno")
        self.events_var = tk.StringVar(value="0 eventos")
        self.last_event_var = tk.StringVar(value="Sin actividad registrada")
        self.record_help_var = tk.StringVar(
            value="Al iniciar, la aplicación cambiará a la ventana objetivo y mostrará una cuenta regresiva."
        )

        self._configure_styles()
        self._build_ui()
        self._build_overlay()
        self.refresh_presets()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(80, self._poll_engine)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Studio.TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("Studio.TLabel", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI Semibold", 22))
        style.configure("Subtitle.TLabel", background=self.BG, foreground=self.MUTED, font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI Semibold", 12))
        style.configure(
            "Primary.TButton",
            background=self.ACCENT_DARK,
            foreground="white",
            borderwidth=0,
            padding=(14, 9),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Primary.TButton", background=[("active", self.ACCENT), ("disabled", "#244158")])
        style.configure(
            "Secondary.TButton",
            background=self.PANEL_ALT,
            foreground=self.TEXT,
            borderwidth=0,
            padding=(12, 8),
            font=("Segoe UI", 10),
        )
        style.map("Secondary.TButton", background=[("active", "#223251"), ("disabled", "#172033")])
        style.configure(
            "Danger.TButton",
            background="#7f1d1d",
            foreground="white",
            borderwidth=0,
            padding=(12, 8),
            font=("Segoe UI", 10),
        )
        style.map("Danger.TButton", background=[("active", self.DANGER), ("disabled", "#42202a")])
        style.configure(
            "Studio.TEntry",
            fieldbackground="#0b1220",
            foreground=self.TEXT,
            insertcolor=self.TEXT,
            bordercolor="#283750",
            padding=8,
        )
        style.configure(
            "Studio.TCombobox",
            fieldbackground="#0b1220",
            background="#0b1220",
            foreground=self.TEXT,
            arrowcolor=self.TEXT,
            padding=7,
        )
        style.configure(
            "Treeview",
            background="#0b1220",
            fieldbackground="#0b1220",
            foreground=self.TEXT,
            rowheight=38,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=self.PANEL_ALT,
            foreground=self.MUTED,
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map("Treeview", background=[("selected", self.ACCENT_DARK)], foreground=[("selected", "white")])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Studio.TFrame", padding=24)
        root.pack(fill="both", expand=True)
        header = ttk.Frame(root, style="Studio.TFrame")
        header.pack(fill="x", pady=(0, 20))
        ttk.Label(header, text="Window Macro Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Presets independientes, grabación guiada y feedback en tiempo real.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        content = ttk.Frame(root, style="Studio.TFrame")
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)
        left = ttk.Frame(content, style="Panel.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(content, style="Panel.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        ttk.Label(left, text="Presets", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Cada preset conserva su propia grabación y cantidad de eventos.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 12))
        table_frame = ttk.Frame(left, style="Panel.TFrame")
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, columns=("events",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Nombre")
        self.tree.heading("events", text="Eventos")
        self.tree.column("#0", width=350, anchor="w")
        self.tree.column("events", width=100, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)
        self.tree.bind("<Double-1>", lambda _event: self.select_current_preset())

        preset_buttons = ttk.Frame(left, style="Panel.TFrame")
        preset_buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(preset_buttons, text="＋ Crear", style="Primary.TButton", command=self.create_preset).pack(side="left")
        ttk.Button(preset_buttons, text="Renombrar", style="Secondary.TButton", command=self.rename_preset).pack(side="left", padx=8)
        ttk.Button(preset_buttons, text="Eliminar", style="Danger.TButton", command=self.delete_preset).pack(side="left")
        ttk.Button(preset_buttons, text="Actualizar", style="Secondary.TButton", command=self.refresh_presets).pack(side="right")

        ttk.Label(right, text="Ventana objetivo", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(right, text="Ejecutable (.exe)", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        ttk.Entry(right, textvariable=self.exe_var, style="Studio.TEntry").pack(fill="x")
        ttk.Label(right, text="Título contiene (opcional)", style="Muted.TLabel").pack(anchor="w", pady=(9, 4))
        ttk.Entry(right, textvariable=self.title_var, style="Studio.TEntry").pack(fill="x")
        self.connect_button = ttk.Button(
            right,
            text="Conectar a la ventana",
            style="Primary.TButton",
            command=self.connect_target,
        )
        self.connect_button.pack(fill="x", pady=(12, 14))
        tk.Frame(right, height=1, bg="#283750").pack(fill="x", pady=(0, 14))

        active_row = ttk.Frame(right, style="Panel.TFrame")
        active_row.pack(fill="x")
        active_text = ttk.Frame(active_row, style="Panel.TFrame")
        active_text.pack(side="left", fill="x", expand=True)
        ttk.Label(active_text, text="Preset activo", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(active_text, textvariable=self.active_var, style="CardTitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(active_row, textvariable=self.events_var, style="Muted.TLabel").pack(side="right", anchor="e")
        ttk.Label(right, textvariable=self.last_event_var, style="Muted.TLabel", wraplength=330).pack(
            anchor="w", pady=(4, 9)
        )
        ttk.Button(
            right,
            text="Seleccionar preset",
            style="Secondary.TButton",
            command=self.select_current_preset,
        ).pack(fill="x", pady=(0, 7))

        hint = tk.Frame(right, bg="#0b2238", highlightbackground="#164e63", highlightthickness=1)
        hint.pack(fill="x", pady=(0, 8))
        tk.Label(
            hint,
            textvariable=self.record_help_var,
            bg="#0b2238",
            fg="#bae6fd",
            justify="left",
            wraplength=315,
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
        ).pack(fill="x")

        self.record_button = ttk.Button(
            right,
            text="● Preparar grabación (F9)",
            style="Primary.TButton",
            command=self.toggle_recording,
        )
        self.record_button.pack(fill="x", pady=4)
        self.play_button = ttk.Button(
            right,
            text="▶ Ejecutar preset (F10)",
            style="Secondary.TButton",
            command=self.play_selected,
        )
        self.play_button.pack(fill="x", pady=4)
        self.stop_button = ttk.Button(
            right,
            text="■ Detener ejecución (F12)",
            style="Danger.TButton",
            command=self.stop_playback,
        )
        self.stop_button.pack(fill="x", pady=4)

        speed_frame = ttk.Frame(right, style="Panel.TFrame")
        speed_frame.pack(fill="x", pady=(11, 0))
        ttk.Label(speed_frame, text="Velocidad", style="Muted.TLabel").pack(side="left")
        speed = ttk.Combobox(
            speed_frame,
            textvariable=self.speed_var,
            values=(0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
            state="readonly",
            width=8,
            style="Studio.TCombobox",
        )
        speed.pack(side="right")
        speed.bind("<<ComboboxSelected>>", lambda _event: self._apply_speed())

        ttk.Label(right, text="Actividad reciente", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        self.activity = tk.Text(
            right,
            height=5,
            bg="#0b1220",
            fg=self.MUTED,
            insertbackground=self.TEXT,
            relief="flat",
            bd=0,
            padx=8,
            pady=7,
            font=("Consolas", 8),
            wrap="word",
            state="disabled",
        )
        self.activity.pack(fill="both", expand=False)

        status = ttk.Frame(root, style="Panel.TFrame", padding=(16, 12))
        status.pack(fill="x", pady=(18, 0))
        self.status_dot = tk.Canvas(status, width=12, height=12, bg=self.PANEL, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 9))
        self._draw_status_dot(self.MUTED)
        status_text = ttk.Frame(status, style="Panel.TFrame")
        status_text.pack(side="left", fill="x", expand=True)
        ttk.Label(status_text, textvariable=self.status_var, style="Studio.TLabel").pack(anchor="w")
        ttk.Label(status_text, textvariable=self.detail_var, style="Muted.TLabel").pack(anchor="w")

    def _build_overlay(self) -> None:
        self.overlay = tk.Toplevel(self)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg="#020617")
        self.overlay_frame = tk.Frame(
            self.overlay,
            bg="#020617",
            highlightbackground=self.ACCENT,
            highlightthickness=2,
            padx=16,
            pady=10,
        )
        self.overlay_frame.pack(fill="both", expand=True)
        self.overlay_title = tk.Label(
            self.overlay_frame,
            text="PREPARADO",
            bg="#020617",
            fg=self.TEXT,
            font=("Segoe UI Semibold", 12),
        )
        self.overlay_title.pack()
        self.overlay_detail = tk.Label(
            self.overlay_frame,
            text="",
            bg="#020617",
            fg=self.MUTED,
            font=("Segoe UI", 9),
        )
        self.overlay_detail.pack(pady=(2, 0))
        try:
            self.overlay.focusmodel("passive")
        except tk.TclError:
            pass

    def _show_overlay(self, title: str, detail: str, color: str) -> None:
        self.overlay_title.configure(text=title, fg=color)
        self.overlay_detail.configure(text=detail)
        self.overlay_frame.configure(highlightbackground=color)
        self.overlay.update_idletasks()
        width = max(self.overlay.winfo_reqwidth(), 210)
        height = max(self.overlay.winfo_reqheight(), 70)
        x = self.winfo_screenwidth() - width - 28
        self.overlay.geometry(f"{width}x{height}+{x}+28")
        if self.overlay.state() == "withdrawn":
            self.overlay.deiconify()
            self.overlay.lift()

    def _hide_overlay(self) -> None:
        try:
            self.overlay.withdraw()
        except tk.TclError:
            pass

    def _beep(self, frequency: int = 900, duration: int = 100) -> None:
        try:
            winsound.Beep(frequency, duration)
        except (RuntimeError, OSError):
            try:
                winsound.MessageBeep()
            except RuntimeError:
                pass

    def _draw_status_dot(self, color: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 10, 10, fill=color, outline=color)

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.activity.configure(state="normal")
        self.activity.insert("end", f"[{stamp}] {message}\n")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def selected_name(self) -> str | None:
        selection = self.tree.selection()
        return str(self.tree.item(selection[0], "text")) if selection else None

    def refresh_presets(self, select_name: str | None = None) -> None:
        current = select_name or self.selected_name() or self.active_var.get()
        self.tree.delete(*self.tree.get_children())
        selected_item: str | None = None
        for preset in self.store.list_presets():
            item = self.tree.insert("", "end", text=preset.name, values=(preset.event_count,))
            if preset.name == current:
                selected_item = item
        if selected_item:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
            self.tree.see(selected_item)

    def _on_selection(self, _event: object | None = None) -> None:
        name = self.selected_name()
        if not name:
            return
        preset = next((item for item in self.store.list_presets() if item.name == name), None)
        count = preset.event_count if preset else 0
        self.detail_var.set(f"Seleccionado: {name} · {count} eventos")

    def create_preset(self) -> None:
        if self._engine_busy() or self.recording_armed:
            messagebox.showwarning("Operación no disponible", "Detén o cancela la operación actual.", parent=self)
            return
        name = simpledialog.askstring("Crear preset", "Nombre del nuevo preset:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name.casefold() in {existing.casefold() for existing in self.store.names()}:
            messagebox.showwarning("Preset existente", "Ya existe un preset con ese nombre.", parent=self)
            return
        payload = {"version": 2, "preset": {"name": name}, "target": {}, "events": []}
        self.store.path_for(name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.refresh_presets(name)
        self._log(f"Preset creado: {name}")
        if self.recorder:
            self.recorder.select_preset(name)
            self._sync_active()

    def rename_preset(self) -> None:
        old_name = self.selected_name()
        if not old_name:
            messagebox.showinfo("Renombrar", "Selecciona un preset.", parent=self)
            return
        if self._engine_busy() or self.recording_armed:
            messagebox.showwarning("Operación no disponible", "Detén o cancela la operación actual.", parent=self)
            return
        new_name = simpledialog.askstring(
            "Renombrar preset",
            "Nuevo nombre:",
            initialvalue=old_name,
            parent=self,
        )
        if not new_name or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if new_name.casefold() in {name.casefold() for name in self.store.names() if name != old_name}:
            messagebox.showwarning("Nombre ocupado", "Ya existe otro preset con ese nombre.", parent=self)
            return
        old_path = next((preset.path for preset in self.store.list_presets() if preset.name == old_name), None)
        if not old_path:
            return
        new_path = self.store.path_for(new_name)
        payload = json.loads(old_path.read_text(encoding="utf-8"))
        payload.setdefault("preset", {})["name"] = new_name
        new_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if old_path.resolve() != new_path.resolve():
            old_path.unlink(missing_ok=True)
        if self.recorder and self.recorder.active_preset == old_name:
            self.recorder.select_preset(new_name)
        self.refresh_presets(new_name)
        self._sync_active()
        self._log(f"Preset renombrado: {old_name} → {new_name}")

    def delete_preset(self) -> None:
        name = self.selected_name()
        if not name:
            messagebox.showinfo("Eliminar", "Selecciona un preset.", parent=self)
            return
        if self._engine_busy() or self.recording_armed:
            messagebox.showwarning("Operación no disponible", "Detén o cancela la operación actual.", parent=self)
            return
        if not messagebox.askyesno("Eliminar preset", f"¿Eliminar permanentemente '{name}'?", parent=self):
            return
        preset = next((item for item in self.store.list_presets() if item.name == name), None)
        if preset:
            preset.path.unlink(missing_ok=True)
        if self.recorder and self.recorder.active_preset == name:
            remaining = self.store.names()
            if remaining:
                self.recorder.select_preset(remaining[0])
            else:
                self.recorder.events = []
                self.recorder.active_preset = "Ninguno"
        self.refresh_presets()
        self._sync_active()
        self.detail_var.set(f"Preset '{name}' eliminado.")
        self._log(f"Preset eliminado: {name}")

    def connect_target(self) -> None:
        exe = self.exe_var.get().strip()
        if not exe:
            messagebox.showwarning("Ejecutable requerido", "Escribe el nombre del archivo .exe.", parent=self)
            return
        self._shutdown_engine()
        try:
            target = TargetWindow(exe, self.title_var.get().strip() or None)
            active = self.selected_name() or (self.store.names()[0] if self.store.names() else "Ejecución 1")
            recorder = WindowMacroRecorder(target, self.store, active, playback_speed=float(self.speed_var.get()))
            recorder.mouse_listener = mouse.Listener(
                on_move=recorder.on_mouse_move,
                on_click=recorder.on_mouse_click,
                on_scroll=recorder.on_mouse_scroll,
            )
            recorder.keyboard_listener = keyboard.Listener(
                on_press=recorder.on_key_press,
                on_release=recorder.on_key_release,
                win32_event_filter=recorder.on_win32_keyboard_event,
            )
            recorder.mouse_listener.start()
            recorder.keyboard_listener.start()
            self.recorder = recorder
            self._last_recording = False
            self._last_replaying = False
            self._last_status_message = ""
            self._last_event_count = -1
            self.status_var.set("Conectado")
            self.detail_var.set(f"{target.title} · PID {target.pid}")
            self._draw_status_dot(self.SUCCESS)
            self._sync_active()
            self.refresh_presets(active)
            self._log(f"Conectado a {target.title} (PID {target.pid})")
        except Exception as exc:
            self.recorder = None
            self.status_var.set("No se pudo conectar")
            self.detail_var.set(str(exc))
            self._draw_status_dot(self.DANGER)
            self._log(f"Error de conexión: {exc}")
            messagebox.showerror("Error de conexión", str(exc), parent=self)

    def select_current_preset(self, show_message: bool = True) -> bool:
        name = self.selected_name()
        if not name:
            if show_message:
                messagebox.showinfo("Seleccionar preset", "Selecciona un preset de la lista.", parent=self)
            return False
        if not self.recorder:
            self.active_var.set(name)
            preset = next((item for item in self.store.list_presets() if item.name == name), None)
            self.events_var.set(f"{preset.event_count if preset else 0} eventos")
            self.detail_var.set("Preset preparado. Conecta una ventana para grabar o ejecutarlo.")
            return True
        if self._engine_busy() or self.recording_armed:
            if show_message:
                messagebox.showwarning("Preset ocupado", "Detén o cancela la operación actual.", parent=self)
            return False
        if self.recorder.active_preset != name:
            self.recorder.select_preset(name)
            self._log(f"Preset activo: {name}")
        self._sync_active()
        return True

    def toggle_recording(self) -> None:
        if not self._require_engine():
            return
        assert self.recorder is not None
        if self.recorder.recording:
            count = self.recorder.stop_recording()
            self._last_recording = False
            self._finish_recording_feedback(count)
            return
        if self.recording_armed:
            self._cancel_recording_arm("Preparación cancelada por el usuario.")
            return
        if self.recorder.replaying:
            messagebox.showwarning("Grabación no disponible", "Detén primero la ejecución actual.", parent=self)
            return
        if not self.select_current_preset(show_message=True):
            return
        if self.recorder.events:
            replace = messagebox.askyesno(
                "Reemplazar grabación",
                f"'{self.recorder.active_preset}' ya tiene {len(self.recorder.events)} eventos.\n\n"
                "¿Deseas reemplazar esa grabación?",
                parent=self,
            )
            if not replace:
                return
        self._arm_recording()

    def _arm_recording(self) -> None:
        assert self.recorder is not None
        self.recording_armed = True
        self.recording_deadline = time.perf_counter() + self.ARM_TIMEOUT_SECONDS
        self.countdown_remaining = None
        self.next_countdown_tick = 0.0
        self.record_button.configure(text="✕ Cancelar preparación")
        self.status_var.set("Preparando grabación")
        self.detail_var.set(
            f"Activando '{self.recorder.target.title}'. La grabación comenzará tras una cuenta regresiva."
        )
        self.record_help_var.set("Espera la cuenta regresiva 3–2–1. Un sonido confirma el inicio real de la captura.")
        self._draw_status_dot(self.WARNING)
        self._show_overlay("PREPARANDO", "Cambiando a la ventana objetivo…", self.WARNING)
        self._log(f"Grabación preparada para '{self.recorder.active_preset}'")
        self.after(180, self._try_activate_record_target)

    def _try_activate_record_target(self) -> None:
        if not self.recording_armed or not self.recorder:
            return
        if not self.recorder.target.activate():
            self.detail_var.set(
                "Windows no permitió activar la ventana automáticamente. Cámbiate manualmente a la ventana objetivo."
            )
            self._show_overlay("ESPERANDO", "Cambia manualmente a la ventana objetivo", self.WARNING)
            self._log("La activación automática falló; esperando cambio manual de ventana")

    def _poll_recording_arm(self) -> None:
        if not self.recording_armed or not self.recorder:
            return
        now = time.perf_counter()
        if now >= self.recording_deadline:
            self._cancel_recording_arm("No se activó la ventana objetivo dentro de 15 segundos.", error=True)
            return
        if not self.recorder.target.is_foreground():
            if self.countdown_remaining is not None:
                self.countdown_remaining = None
                self._show_overlay("ESPERANDO", "La ventana objetivo debe permanecer activa", self.WARNING)
            remaining = max(0, int(self.recording_deadline - now + 0.999))
            self.detail_var.set(f"Esperando la ventana objetivo… quedan {remaining} segundos.")
            return
        if self.countdown_remaining is None:
            self.countdown_remaining = self.COUNTDOWN_SECONDS
            self.next_countdown_tick = now
        if now < self.next_countdown_tick:
            return
        if self.countdown_remaining and self.countdown_remaining > 0:
            number = self.countdown_remaining
            self._show_overlay("GRABACIÓN", f"Comienza en {number}", self.WARNING)
            self.status_var.set(f"Grabación comienza en {number}")
            self.detail_var.set("Mantén la ventana objetivo activa.")
            self._beep(650 + (self.COUNTDOWN_SECONDS - number) * 100, 90)
            self.countdown_remaining -= 1
            self.next_countdown_tick = now + 1.0
            return
        if self.recorder.start_recording():
            self.recording_armed = False
            self.countdown_remaining = None
            self._show_overlay("● GRABANDO", "0 eventos capturados", self.DANGER)
            self.record_help_var.set("Grabación activa. Pulsa F9 en la ventana objetivo o vuelve aquí y pulsa Detener.")
            self._beep(1100, 150)
            self._log(f"Grabación iniciada: {self.recorder.active_preset}")
        else:
            self.countdown_remaining = None
            self.next_countdown_tick = 0.0

    def _cancel_recording_arm(self, reason: str, error: bool = False) -> None:
        self.recording_armed = False
        self.countdown_remaining = None
        self.recording_deadline = 0.0
        self._hide_overlay()
        self.record_button.configure(text="● Preparar grabación (F9)")
        self.record_help_var.set(
            "Al iniciar, la aplicación cambiará a la ventana objetivo y mostrará una cuenta regresiva."
        )
        self.status_var.set("Preparación cancelada" if not error else "No se inició la grabación")
        self.detail_var.set(reason)
        self._draw_status_dot(self.WARNING if not error else self.DANGER)
        self._log(reason)
        self._beep(420, 130)

    def _finish_recording_feedback(self, count: int) -> None:
        self.recording_armed = False
        self._hide_overlay()
        self.refresh_presets(self.recorder.active_preset if self.recorder else None)
        self.record_button.configure(text="● Preparar grabación (F9)")
        self.record_help_var.set(
            "Al iniciar, la aplicación cambiará a la ventana objetivo y mostrará una cuenta regresiva."
        )
        self.status_var.set("Grabación guardada")
        if count > 0:
            self.detail_var.set(f"Se guardaron correctamente {count} eventos.")
            self._draw_status_dot(self.SUCCESS)
            self._beep(1200, 100)
            self._beep(1500, 100)
        else:
            self.detail_var.set(
                "La grabación terminó con 0 eventos. Comprueba que la ventana objetivo estuvo activa y que interactuaste dentro de ella."
            )
            self._draw_status_dot(self.WARNING)
            self._beep(380, 180)
        self._log(f"Grabación guardada: {count} eventos")
        self._sync_active()

    def play_selected(self) -> None:
        if not self._require_engine():
            return
        assert self.recorder is not None
        if self.recording_armed:
            self._cancel_recording_arm("Preparación cancelada para ejecutar el preset.")
        if not self.select_current_preset(show_message=True):
            return
        self._apply_speed()
        if not self.recorder.events:
            messagebox.showwarning(
                "Preset vacío",
                "El preset seleccionado no contiene eventos. Grábalo antes de ejecutarlo.",
                parent=self,
            )
            self.status_var.set("Preset vacío")
            self.detail_var.set("No hay eventos que ejecutar.")
            self._draw_status_dot(self.WARNING)
            return
        if self.recorder.start_playback():
            self.status_var.set("Preparando ejecución")
            self.detail_var.set(
                f"Ejecutando '{self.recorder.active_preset}' a velocidad {self.recorder.playback_speed:g}×."
            )
            self._draw_status_dot(self.ACCENT)
            self._show_overlay("▶ EJECUTANDO", f"0 / {len(self.recorder.events)} eventos", self.ACCENT)
            self._log(f"Ejecución iniciada: {self.recorder.active_preset}")
        else:
            snapshot = self.recorder.status_snapshot()
            self.status_var.set("No se pudo ejecutar")
            self.detail_var.set(str(snapshot["status_message"]))
            self._draw_status_dot(self.DANGER)

    def stop_playback(self) -> None:
        if not self._require_engine():
            return
        assert self.recorder is not None
        if self.recorder.stop_playback():
            self.detail_var.set("Deteniendo la ejecución de forma segura…")
            self._log("Se solicitó detener la ejecución")

    def _apply_speed(self) -> None:
        if self.recorder:
            self.recorder.playback_speed = float(self.speed_var.get())

    def _require_engine(self) -> bool:
        if self.recorder:
            return True
        messagebox.showinfo("Sin conexión", "Conecta primero la ventana objetivo.", parent=self)
        return False

    def _engine_busy(self) -> bool:
        return bool(self.recorder and (self.recorder.recording or self.recorder.replaying))

    def _sync_active(self, snapshot: dict[str, object] | None = None) -> None:
        if not self.recorder:
            return
        snapshot = snapshot or self.recorder.status_snapshot()
        event_count = int(snapshot["event_count"])
        self.active_var.set(self.recorder.active_preset)
        self.events_var.set(f"{event_count} eventos")
        last_event_type = str(snapshot["last_event_type"])
        if last_event_type:
            self.last_event_var.set(f"Último evento detectado: {EVENT_LABELS.get(last_event_type, last_event_type)}")
        elif event_count:
            self.last_event_var.set("Grabación cargada y lista para ejecutar")
        else:
            self.last_event_var.set("Sin actividad registrada")

        if self.recording_armed:
            self.record_button.configure(text="✕ Cancelar preparación")
            self.play_button.state(["disabled"])
            self.stop_button.state(["disabled"])
            return
        if bool(snapshot["recording"]):
            self.record_button.configure(text="■ Detener y guardar grabación (F9)")
            self.record_button.state(["!disabled"])
            self.play_button.state(["disabled"])
            self.stop_button.state(["disabled"])
            self.status_var.set("Grabando correctamente")
            self.detail_var.set(f"Capturando entradas en '{self.recorder.active_preset}'.")
            self._draw_status_dot(self.DANGER)
        elif bool(snapshot["replaying"]):
            self.record_button.configure(text="● Preparar grabación (F9)")
            self.record_button.state(["disabled"])
            self.play_button.state(["disabled"])
            self.stop_button.state(["!disabled"])
            self.status_var.set("Ejecutando preset")
            self._draw_status_dot(self.ACCENT)
        else:
            self.record_button.configure(text="● Preparar grabación (F9)")
            self.record_button.state(["!disabled"])
            self.play_button.state(["!disabled"])
            self.stop_button.state(["disabled"])
            if self.status_var.get() not in {
                "Grabación guardada",
                "No se inició la grabación",
                "Preset vacío",
                "Ejecución finalizada",
                "Ejecución detenida",
                "Ejecución abortada",
            }:
                self.status_var.set("Conectado y listo")
                self._draw_status_dot(self.SUCCESS)

    def _handle_engine_transitions(self, snapshot: dict[str, object]) -> None:
        recording = bool(snapshot["recording"])
        replaying = bool(snapshot["replaying"])
        event_count = int(snapshot["event_count"])
        if recording and not self._last_recording:
            self.recording_armed = False
            self._show_overlay("● GRABANDO", f"{event_count} eventos capturados", self.DANGER)
            if self.recorder and not self.recorder.target.is_foreground():
                self.after(40, self.recorder.target.activate)
            self._beep(1100, 140)
            self._log(f"Grabación activa: {self.recorder.active_preset if self.recorder else ''}")
        if recording:
            last_label = EVENT_LABELS.get(str(snapshot["last_event_type"]), "esperando actividad")
            self._show_overlay("● GRABANDO", f"{event_count} eventos · {last_label}", self.DANGER)
        if not recording and self._last_recording:
            self._finish_recording_feedback(event_count)
        if replaying:
            self._show_overlay(
                "▶ EJECUTANDO",
                f"{int(snapshot['playback_index'])} / {int(snapshot['playback_total'])} eventos",
                self.ACCENT,
            )
        if not replaying and self._last_replaying:
            outcome = str(snapshot["playback_outcome"])
            self._hide_overlay()
            if outcome == "completed":
                self.status_var.set("Ejecución finalizada")
                self.detail_var.set("El preset terminó correctamente.")
                self._draw_status_dot(self.SUCCESS)
                self._beep(1300, 120)
                self._log("Ejecución finalizada correctamente")
            elif outcome == "stopped":
                self.status_var.set("Ejecución detenida")
                self.detail_var.set("La ejecución fue detenida por el usuario.")
                self._draw_status_dot(self.WARNING)
                self._log("Ejecución detenida")
            else:
                self.status_var.set("Ejecución abortada")
                self.detail_var.set(str(snapshot["status_message"]))
                self._draw_status_dot(self.DANGER)
                self._beep(400, 160)
                self._log(f"Ejecución abortada: {snapshot['status_message']}")

        status_message = str(snapshot["status_message"])
        if status_message and status_message != self._last_status_message:
            self._last_status_message = status_message
            if not self.recording_armed and not recording:
                self.detail_var.set(status_message)
        if event_count != self._last_event_count:
            self._last_event_count = event_count
            self.events_var.set(f"{event_count} eventos")
        self._last_recording = recording
        self._last_replaying = replaying

    def _poll_engine(self) -> None:
        if self._closing:
            return
        if self.recorder:
            try:
                self.recorder._drain_commands()
                if not self.recorder.target.is_valid():
                    self.status_var.set("Ventana cerrada")
                    self.detail_var.set("La ventana objetivo ya no está disponible.")
                    self._draw_status_dot(self.DANGER)
                    self._log("La ventana objetivo se cerró")
                    self._shutdown_engine()
                else:
                    self._poll_recording_arm()
                    snapshot = self.recorder.status_snapshot()
                    self._handle_engine_transitions(snapshot)
                    self._sync_active(snapshot)
            except Exception as exc:
                self.status_var.set("Error del motor")
                self.detail_var.set(f"Error: {exc}")
                self._draw_status_dot(self.DANGER)
                self._log(f"Error del motor: {exc}")
        self.after(80, self._poll_engine)

    def _shutdown_engine(self) -> None:
        self.recording_armed = False
        self.countdown_remaining = None
        self._hide_overlay()
        if not self.recorder:
            return
        recorder = self.recorder
        self.recorder = None
        try:
            recorder.shutdown()
            if recorder.mouse_listener:
                recorder.mouse_listener.join(timeout=0.5)
            if recorder.keyboard_listener:
                recorder.keyboard_listener.join(timeout=0.5)
        except Exception:
            pass

    def close_app(self) -> None:
        self._closing = True
        self._shutdown_engine()
        try:
            self.overlay.destroy()
        except tk.TclError:
            pass
        self.destroy()


def main() -> None:
    MacroStudio().mainloop()


if __name__ == "__main__":
    main()
