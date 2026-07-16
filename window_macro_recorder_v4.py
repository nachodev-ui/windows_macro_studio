from __future__ import annotations

import argparse
import json
import math
import queue
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil
import win32con
import win32gui
import win32process
from pynput import keyboard, mouse


RESERVED_KEYS = {
    keyboard.Key.f6,
    keyboard.Key.f7,
    keyboard.Key.f8,
    keyboard.Key.f9,
    keyboard.Key.f10,
    keyboard.Key.f12,
}
RESERVED_VK_CODES = {0x75, 0x76, 0x77, 0x78, 0x79, 0x7B}
HOTKEY_COMMANDS = {
    0x75: "previous_preset",
    0x76: "next_preset",
    0x77: "shutdown",
    0x78: "toggle_recording",
    0x79: "start_playback",
    0x7B: "stop_playback",
}
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105


@dataclass(slots=True)
class RecordedEvent:
    time: float
    type: str
    data: dict[str, Any]


@dataclass(slots=True)
class WindowCandidate:
    hwnd: int
    pid: int
    title: str


@dataclass(slots=True)
class PresetInfo:
    name: str
    path: Path
    event_count: int


class PresetStore:
    """Gestiona una carpeta con una macro JSON independiente por preset."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_filename(name: str) -> str:
        cleaned = unicodedata.normalize("NFKD", name)
        cleaned = cleaned.encode("ascii", "ignore").decode("ascii")
        cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", cleaned)
        cleaned = re.sub(r"[\s-]+", "_", cleaned).strip("._")
        return cleaned or "preset"

    @staticmethod
    def _natural_key(value: str) -> list[Any]:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]

    def path_for(self, name: str) -> Path:
        return self.directory / f"{self._safe_filename(name)}.json"

    def list_presets(self) -> list[PresetInfo]:
        presets: list[PresetInfo] = []
        for path in self.directory.glob("*.json"):
            name = path.stem.replace("_", " ")
            event_count = 0
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                name = str(payload.get("preset", {}).get("name") or name)
                events = payload.get("events", [])
                event_count = len(events) if isinstance(events, list) else 0
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            presets.append(PresetInfo(name=name, path=path, event_count=event_count))
        presets.sort(key=lambda item: self._natural_key(item.name))
        return presets

    def names(self) -> list[str]:
        return [preset.name for preset in self.list_presets()]

    def choose_interactively(self) -> str:
        presets = self.list_presets()
        print("\n=== Presets de grabación ===")
        if presets:
            for index, preset in enumerate(presets, start=1):
                print(f"  {index}. {preset.name} ({preset.event_count} eventos)")
            print("  N. Crear un preset nuevo")
            while True:
                raw = input("Selecciona un preset: ").strip()
                if raw.casefold() in {"n", "nuevo", "new"}:
                    return self._ask_new_name(presets)
                try:
                    selected = int(raw)
                except ValueError:
                    print("Escribe el número del preset o N para crear uno.")
                    continue
                if 1 <= selected <= len(presets):
                    return presets[selected - 1].name
                print("Selección fuera de rango.")
        print("Todavía no existen presets.")
        return self._ask_new_name(presets)

    def _ask_new_name(self, existing: list[PresetInfo] | None = None) -> str:
        existing_names = {item.name.casefold() for item in (existing or self.list_presets())}
        suggested_number = 1
        while f"ejecución {suggested_number}".casefold() in existing_names:
            suggested_number += 1
        suggested = f"Ejecución {suggested_number}"
        while True:
            raw = input(f"Nombre del nuevo preset [{suggested}]: ").strip()
            name = raw or suggested
            if name.casefold() in existing_names:
                print("Ese preset ya existe; selecciónalo o usa otro nombre.")
                continue
            return name


class TargetWindow:
    def __init__(self, executable_name: str, title_contains: str | None = None) -> None:
        self.executable_name = executable_name.lower()
        self.title_contains = title_contains.lower() if title_contains else None
        self.hwnd = self._select_window()
        _, self.pid = win32process.GetWindowThreadProcessId(self.hwnd)
        self.title = win32gui.GetWindowText(self.hwnd)

    def _find_candidates(self) -> list[WindowCandidate]:
        candidates: list[WindowCandidate] = []

        def callback(hwnd: int, _: Any) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = psutil.Process(pid).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                return True
            if process_name != self.executable_name:
                return True
            if self.title_contains and self.title_contains not in title.lower():
                return True
            candidates.append(WindowCandidate(hwnd=hwnd, pid=pid, title=title))
            return True

        win32gui.EnumWindows(callback, None)
        return candidates

    def _select_window(self) -> int:
        candidates = self._find_candidates()
        if not candidates:
            title_help = f" y título que contenga '{self.title_contains}'" if self.title_contains else ""
            raise RuntimeError(
                f"No encontré una ventana visible de '{self.executable_name}'{title_help}. "
                "Abre la aplicación y vuelve a intentarlo."
            )
        if len(candidates) == 1:
            return candidates[0].hwnd
        candidates.sort(key=lambda item: item.pid)
        return candidates[0].hwnd

    def is_valid(self) -> bool:
        return bool(win32gui.IsWindow(self.hwnd))

    def is_foreground(self) -> bool:
        return self.is_valid() and win32gui.GetForegroundWindow() == self.hwnd

    def activate(self) -> bool:
        if not self.is_valid():
            return False
        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.hwnd)
        except win32gui.error:
            return False
        time.sleep(0.25)
        return self.is_foreground()

    def client_bounds(self) -> tuple[int, int, int, int]:
        if not self.is_valid():
            raise RuntimeError("La ventana objetivo ya no existe.")
        left, top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(self.hwnd)
        return left, top, client_right - client_left, client_bottom - client_top

    def screen_to_normalized(self, x: int, y: int) -> tuple[float, float] | None:
        left, top, width, height = self.client_bounds()
        if width <= 1 or height <= 1:
            return None
        if not (left <= x < left + width and top <= y < top + height):
            return None
        return (x - left) / (width - 1), (y - top) / (height - 1)

    def normalized_to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        left, top, width, height = self.client_bounds()
        if width <= 1 or height <= 1:
            raise RuntimeError("El área cliente de la ventana no tiene un tamaño válido.")
        clamped_x = min(max(nx, 0.0), 1.0)
        clamped_y = min(max(ny, 0.0), 1.0)
        return left + round(clamped_x * (width - 1)), top + round(clamped_y * (height - 1))


class WindowMacroRecorder:
    def __init__(
        self,
        target: TargetWindow,
        preset_store: PresetStore,
        preset_name: str,
        playback_speed: float = 1.0,
        mouse_sample_interval: float = 0.012,
        mouse_min_distance: float = 2.0,
    ) -> None:
        if playback_speed <= 0:
            raise ValueError("La velocidad de reproducción debe ser mayor que cero.")
        self.target = target
        self.preset_store = preset_store
        self.active_preset = preset_name
        self.playback_speed = playback_speed
        self.mouse_sample_interval = mouse_sample_interval
        self.mouse_min_distance = mouse_min_distance
        self.events: list[RecordedEvent] = []
        self.recording = False
        self.replaying = False
        self.recording_started_at = 0.0
        self.last_mouse_sample_at = 0.0
        self.last_mouse_position: tuple[int, int] | None = None
        self.state_lock = threading.RLock()
        self.stop_playback_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.command_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.pressed_reserved_vks: set[int] = set()
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()
        self.mouse_listener: mouse.Listener | None = None
        self.keyboard_listener: keyboard.Listener | None = None
        self.last_status_code = "ready"
        self.last_status_message = "Motor preparado."
        self.last_event_type = ""
        self.last_event_at = 0.0
        self.playback_index = 0
        self.playback_total = 0
        self.playback_outcome = "idle"
        self.load(quiet_missing=True)

    @property
    def output_path(self) -> Path:
        return self.preset_store.path_for(self.active_preset)

    def _elapsed(self) -> float:
        return time.perf_counter() - self.recording_started_at

    def _set_status(self, code: str, message: str) -> None:
        with self.state_lock:
            self.last_status_code = code
            self.last_status_message = message

    def status_snapshot(self) -> dict[str, Any]:
        with self.state_lock:
            return {
                "recording": self.recording,
                "replaying": self.replaying,
                "event_count": len(self.events),
                "last_event_type": self.last_event_type,
                "last_event_at": self.last_event_at,
                "status_code": self.last_status_code,
                "status_message": self.last_status_message,
                "playback_index": self.playback_index,
                "playback_total": self.playback_total,
                "playback_outcome": self.playback_outcome,
            }

    def _append_event(self, event_type: str, data: dict[str, Any]) -> None:
        with self.state_lock:
            if not self.recording or self.replaying or not self.target.is_foreground():
                return
            self.events.append(RecordedEvent(time=self._elapsed(), type=event_type, data=data))
            self.last_event_type = event_type
            self.last_event_at = time.perf_counter()

    @staticmethod
    def _serialize_key(key: keyboard.Key | keyboard.KeyCode) -> dict[str, Any] | None:
        if isinstance(key, keyboard.Key):
            return {"kind": "special", "value": key.name}
        vk = getattr(key, "vk", None)
        if vk is not None:
            return {"kind": "vk", "value": int(vk)}
        char = getattr(key, "char", None)
        if char is not None:
            return {"kind": "char", "value": char}
        return None

    @staticmethod
    def _deserialize_key(data: dict[str, Any]) -> keyboard.Key | keyboard.KeyCode | str:
        kind = data["kind"]
        value = data["value"]
        if kind == "special":
            return getattr(keyboard.Key, value)
        if kind == "vk":
            return keyboard.KeyCode.from_vk(int(value))
        if kind == "char":
            return str(value)
        raise ValueError(f"Tipo de tecla no soportado: {kind}")

    def on_mouse_move(self, x: int, y: int) -> None:
        with self.state_lock:
            if not self.recording or self.replaying or not self.target.is_foreground():
                return
        now = time.perf_counter()
        if now - self.last_mouse_sample_at < self.mouse_sample_interval:
            return
        if self.last_mouse_position is not None:
            previous_x, previous_y = self.last_mouse_position
            if math.hypot(x - previous_x, y - previous_y) < self.mouse_min_distance:
                return
        normalized = self.target.screen_to_normalized(x, y)
        if normalized is None:
            return
        self.last_mouse_sample_at = now
        self.last_mouse_position = (x, y)
        nx, ny = normalized
        self._append_event("mouse_move", {"nx": nx, "ny": ny})

    def on_mouse_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        normalized = self.target.screen_to_normalized(x, y)
        if normalized is None:
            return
        nx, ny = normalized
        self._append_event(
            "mouse_click",
            {"nx": nx, "ny": ny, "button": button.name, "pressed": pressed},
        )

    def on_mouse_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        normalized = self.target.screen_to_normalized(x, y)
        if normalized is None:
            return
        nx, ny = normalized
        self._append_event("mouse_scroll", {"nx": nx, "ny": ny, "dx": dx, "dy": dy})

    def on_win32_keyboard_event(self, msg: int, data: Any) -> bool:
        vk_code = int(data.vkCode)
        if vk_code not in RESERVED_VK_CODES:
            return True
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
            if vk_code not in self.pressed_reserved_vks:
                self.pressed_reserved_vks.add(vk_code)
                command = HOTKEY_COMMANDS.get(vk_code)
                if command is not None:
                    self.command_queue.put(command)
        elif msg in (WM_KEYUP, WM_SYSKEYUP):
            self.pressed_reserved_vks.discard(vk_code)
        if self.keyboard_listener is not None:
            self.keyboard_listener.suppress_event()
        return True

    def on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if key in RESERVED_KEYS:
            return None
        serialized = self._serialize_key(key)
        if serialized is not None:
            self._append_event("key_press", {"key": serialized})
        return None

    def on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key in RESERVED_KEYS:
            return
        serialized = self._serialize_key(key)
        if serialized is not None:
            self._append_event("key_release", {"key": serialized})

    def _handle_command(self, command: str) -> None:
        if command == "shutdown":
            self.shutdown()
        elif command == "toggle_recording":
            self.stop_recording() if self.recording else self.start_recording()
        elif command == "start_playback":
            self.start_playback()
        elif command == "stop_playback":
            self.stop_playback()
        elif command == "previous_preset":
            self.cycle_preset(-1)
        elif command == "next_preset":
            self.cycle_preset(1)

    def _drain_commands(self) -> None:
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                return
            self._handle_command(command)

    def cycle_preset(self, direction: int) -> None:
        with self.state_lock:
            if self.recording or self.replaying:
                return
        names = self.preset_store.names()
        if self.active_preset not in names:
            names.append(self.active_preset)
            names.sort(key=self.preset_store._natural_key)
        if len(names) <= 1:
            return
        current_index = names.index(self.active_preset)
        self.select_preset(names[(current_index + direction) % len(names)])

    def select_preset(self, name: str) -> None:
        with self.state_lock:
            self.active_preset = name
            self.events = []
        loaded = self.load(quiet_missing=True)
        suffix = f"{len(self.events)} eventos" if loaded else "sin grabación todavía"
        self._set_status("preset", f"Preset activo: {self.active_preset} ({suffix}).")

    def start_recording(self) -> bool:
        with self.state_lock:
            if self.replaying:
                self.last_status_code = "error"
                self.last_status_message = "No se puede grabar durante la reproducción."
                return False
            if not self.target.is_foreground():
                self.last_status_code = "waiting_focus"
                self.last_status_message = "La ventana objetivo no está en primer plano."
                return False
            self.events.clear()
            self.recording_started_at = time.perf_counter()
            self.last_mouse_sample_at = 0.0
            self.last_mouse_position = None
            self.last_event_type = ""
            self.last_event_at = 0.0
            self.recording = True
            self.last_status_code = "recording"
            self.last_status_message = f"Grabando '{self.active_preset}'."
        return True

    def stop_recording(self) -> int:
        with self.state_lock:
            if not self.recording:
                return len(self.events)
            self.recording = False
            event_count = len(self.events)
        self.save()
        self._set_status(
            "recording_saved",
            f"Grabación guardada: {event_count} eventos en '{self.active_preset}'.",
        )
        return event_count

    def save(self) -> None:
        payload = {
            "version": 2,
            "preset": {"name": self.active_preset},
            "target": {
                "executable": self.target.executable_name,
                "title": self.target.title,
            },
            "events": [asdict(event) for event in self.events],
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.output_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(self.output_path)

    def load(self, quiet_missing: bool = False) -> bool:
        if not self.output_path.exists():
            return False
        try:
            payload = json.loads(self.output_path.read_text(encoding="utf-8"))
            raw_events = payload["events"]
            if not isinstance(raw_events, list):
                raise TypeError("El campo events no es una lista.")
            loaded_events = [RecordedEvent(**item) for item in raw_events]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        with self.state_lock:
            self.events = loaded_events
            self.last_status_code = "loaded"
            self.last_status_message = f"Preset cargado: {len(loaded_events)} eventos."
        return True

    def start_playback(self) -> bool:
        with self.state_lock:
            if self.recording:
                self.last_status_code = "error"
                self.last_status_message = "Termina la grabación antes de reproducir."
                return False
            if self.replaying:
                self.last_status_code = "error"
                self.last_status_message = "La macro ya se está reproduciendo."
                return False
        if not self.events and not self.load():
            self._set_status("empty", f"El preset '{self.active_preset}' no contiene eventos.")
            return False
        if not self.events:
            self._set_status("empty", f"El preset '{self.active_preset}' no contiene eventos.")
            return False
        with self.state_lock:
            self.replaying = True
            self.playback_index = 0
            self.playback_total = len(self.events)
            self.playback_outcome = "starting"
            self.last_status_code = "playback_starting"
            self.last_status_message = f"Preparando reproducción de '{self.active_preset}'."
        self.stop_playback_event.clear()
        threading.Thread(target=self._playback_worker, name="macro-playback", daemon=True).start()
        return True

    def stop_playback(self) -> bool:
        with self.state_lock:
            if not self.replaying:
                self.last_status_code = "idle"
                self.last_status_message = "No hay una reproducción activa."
                return False
            self.playback_outcome = "stopping"
            self.last_status_code = "playback_stopping"
            self.last_status_message = "Deteniendo reproducción..."
        self.stop_playback_event.set()
        return True

    def _playback_worker(self) -> None:
        outcome = "stopped"
        try:
            if not self.target.activate():
                outcome = "focus_error"
                self._set_status(
                    "focus_error",
                    "No se pudo activar la ventana objetivo. Haz clic en ella y vuelve a ejecutar.",
                )
                return
            self._set_status("replaying", f"Ejecutando '{self.active_preset}'.")
            previous_time = 0.0
            for index, event in enumerate(list(self.events), start=1):
                if self.stop_playback_event.is_set() or self.shutdown_event.is_set():
                    outcome = "stopped"
                    break
                delay = max(0.0, (event.time - previous_time) / self.playback_speed)
                previous_time = event.time
                if self.stop_playback_event.wait(delay):
                    outcome = "stopped"
                    break
                if not self.target.is_foreground():
                    outcome = "focus_lost"
                    self._set_status("focus_lost", "La ventana objetivo perdió el foco; ejecución abortada.")
                    break
                self._execute_event(event)
                with self.state_lock:
                    self.playback_index = index
            else:
                outcome = "completed"
                self._set_status("playback_completed", f"Reproducción finalizada: '{self.active_preset}'.")
        except Exception as exc:
            outcome = "error"
            self._set_status("playback_error", f"Error durante la reproducción: {exc}")
        finally:
            self._release_common_inputs()
            with self.state_lock:
                self.playback_outcome = outcome
                self.replaying = False
                if outcome == "stopped":
                    self.last_status_code = "playback_stopped"
                    self.last_status_message = "Reproducción detenida."

    def _execute_event(self, event: RecordedEvent) -> None:
        data = event.data
        if event.type == "mouse_move":
            self.mouse_controller.position = self.target.normalized_to_screen(data["nx"], data["ny"])
            return
        if event.type == "mouse_click":
            self.mouse_controller.position = self.target.normalized_to_screen(data["nx"], data["ny"])
            button = getattr(mouse.Button, data["button"])
            if data["pressed"]:
                self.mouse_controller.press(button)
            else:
                self.mouse_controller.release(button)
            return
        if event.type == "mouse_scroll":
            self.mouse_controller.position = self.target.normalized_to_screen(data["nx"], data["ny"])
            self.mouse_controller.scroll(data["dx"], data["dy"])
            return
        if event.type in {"key_press", "key_release"}:
            key = self._deserialize_key(data["key"])
            if event.type == "key_press":
                self.keyboard_controller.press(key)
            else:
                self.keyboard_controller.release(key)
            return
        raise ValueError(f"Evento no soportado: {event.type}")

    def _release_common_inputs(self) -> None:
        for key in (
            keyboard.Key.shift,
            keyboard.Key.shift_l,
            keyboard.Key.shift_r,
            keyboard.Key.ctrl,
            keyboard.Key.ctrl_l,
            keyboard.Key.ctrl_r,
            keyboard.Key.alt,
            keyboard.Key.alt_l,
            keyboard.Key.alt_r,
            keyboard.Key.cmd,
        ):
            try:
                self.keyboard_controller.release(key)
            except Exception:
                pass
        for button in (mouse.Button.left, mouse.Button.middle, mouse.Button.right):
            try:
                self.mouse_controller.release(button)
            except Exception:
                pass

    def shutdown(self) -> None:
        self._set_status("shutdown", "Cerrando grabador...")
        self.shutdown_event.set()
        self.stop_playback_event.set()
        with self.state_lock:
            was_recording = self.recording
        if was_recording:
            self.stop_recording()
        if self.mouse_listener is not None:
            self.mouse_listener.stop()
        if self.keyboard_listener is not None:
            self.keyboard_listener.stop()

    def run(self) -> None:
        print(f"Ventana objetivo: {self.target.title} (PID {self.target.pid})")
        print(f"Preset activo: {self.active_preset} ({len(self.events)} eventos cargados)")
        self.mouse_listener = mouse.Listener(
            on_move=self.on_mouse_move,
            on_click=self.on_mouse_click,
            on_scroll=self.on_mouse_scroll,
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release,
            win32_event_filter=self.on_win32_keyboard_event,
        )
        self.mouse_listener.start()
        self.keyboard_listener.start()
        try:
            while not self.shutdown_event.wait(0.05):
                self._drain_commands()
                if not self.target.is_valid():
                    break
        except KeyboardInterrupt:
            pass
        finally:
            if not self.shutdown_event.is_set():
                self.shutdown()
            self.mouse_listener.join(timeout=1.0)
            self.keyboard_listener.join(timeout=1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Graba varias macros de mouse/teclado como presets para una ventana de Windows."
    )
    parser.add_argument("--exe", help="Nombre del ejecutable objetivo, por ejemplo: notepad.exe")
    parser.add_argument("--title", help="Texto opcional que debe aparecer en el título de la ventana.")
    parser.add_argument(
        "--presets-dir",
        type=Path,
        default=Path("macros"),
        help="Carpeta donde se guardarán los presets JSON.",
    )
    parser.add_argument("--preset", help="Preset seleccionado sin mostrar el menú inicial.")
    parser.add_argument("--speed", type=float, default=1.0, help="Velocidad de reproducción.")
    parser.add_argument("--list-presets", action="store_true", help="Muestra los presets guardados.")
    return parser.parse_args()


def print_presets(store: PresetStore) -> None:
    presets = store.list_presets()
    if not presets:
        print(f"No hay presets en {store.directory.resolve()}.")
        return
    for preset in presets:
        print(f"- {preset.name}: {preset.event_count} eventos ({preset.path.name})")


def main() -> int:
    args = parse_args()
    try:
        store = PresetStore(args.presets_dir)
        if args.list_presets:
            print_presets(store)
            return 0
        if not args.exe:
            raise ValueError("Debes indicar --exe, salvo cuando uses --list-presets.")
        preset_name = args.preset.strip() if args.preset and args.preset.strip() else store.choose_interactively()
        target = TargetWindow(args.exe, args.title)
        WindowMacroRecorder(target, store, preset_name, args.speed).run()
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
