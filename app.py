"""
ThermoLens — Native GUI Temperature Monitor (Optimized Version)
Lightweight system tray app with customtkinter.
"""

import sys
import os
import ctypes
import time
import math
import platform
import threading
from collections import deque

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# ──────────────────────────────────────────────
# Auto-elevate to administrator (Windows only)
# ──────────────────────────────────────────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if not is_admin():
    script_path = os.path.abspath(sys.argv[0])
    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        " ".join(['"' + script_path + '"'] + sys.argv[1:]),
        None,
        1,
    )
    sys.exit(0)

# ──────────────────────────────────────────────
# Imports that need admin / come after guard
# ──────────────────────────────────────────────
import psutil  # noqa: E402
import customtkinter as ctk  # noqa: E402
import pystray  # noqa: E402
from PIL import Image  # noqa: E402

# ──────────────────────────────────────────────
# Temperature back-ends
# ──────────────────────────────────────────────
_HM = None
_HAS_HARDWARE_MONITOR = False
try:
    from PyLibreHardwareMonitor import Computer
    _HM = Computer()
    _HAS_HARDWARE_MONITOR = True
except Exception as e:
    print(f"Warning: Hardware monitor failed to load ({e}). Using fallback methods.")

DEMO_MODE = not _HAS_HARDWARE_MONITOR

# ──────────────────────────────────────────────
# System info (cached — fetched once)
# ──────────────────────────────────────────────
_SYSTEM_INFO: str | None = None

def get_system_info() -> str:
    global _SYSTEM_INFO
    if _SYSTEM_INFO is not None:
        return _SYSTEM_INFO
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        _SYSTEM_INFO, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
    except Exception:
        _SYSTEM_INFO = platform.processor() or platform.machine()
    return _SYSTEM_INFO

# ──────────────────────────────────────────────
# Demo-mode simulator (smooth + noisy sine)
# ──────────────────────────────────────────────
_rng = None
_sim_start = 0.0

def init_demo_mode():
    global _rng, _sim_start
    import random
    _rng = random.Random(42)
    _sim_start = time.time()

def _sim_temp(base: float, amplitude: float, period: float, noise: float) -> float:
    if _rng is None:
        init_demo_mode()
    elapsed = time.time() - _sim_start
    value = base + amplitude * math.sin(2 * math.pi * elapsed / period)
    value += _rng.gauss(0, noise)
    return round(max(0, value), 1)

def demo_cpu_temp() -> float:
    return _sim_temp(base=57.0, amplitude=17.0, period=120, noise=1.2)

def demo_gpu_temp() -> float:
    return _sim_temp(base=50.0, amplitude=14.0, period=90, noise=1.0)

# ──────────────────────────────────────────────
# Unified reading helpers
# ──────────────────────────────────────────────
def _get_dict_max_temp(hw_dict) -> float | None:
    if not _HAS_HARDWARE_MONITOR or not _HM:
        return None
    try:
        max_temp = None
        for device_name, device_data in hw_dict.items():
            temps = device_data.get('Temperature', {})
            for sensor_name, val in temps.items():
                if val is not None:
                    if max_temp is None or float(val) > max_temp:
                        max_temp = float(val)
        return max_temp
    except Exception:
        return None

def read_cpu_temp() -> float:
    if _HAS_HARDWARE_MONITOR and _HM:
        t = _get_dict_max_temp(_HM.cpu)
        if t is not None:
            return t
    return demo_cpu_temp()

def read_gpu_temp() -> float:
    if _HAS_HARDWARE_MONITOR and _HM:
        t = _get_dict_max_temp(_HM.gpu)
        if t is not None:
            return t
    return demo_gpu_temp()

def _get_dict_total_power(hw_dict) -> float:
    if not _HAS_HARDWARE_MONITOR or not _HM:
        return 0.0
    try:
        total_w = 0.0
        for dev, data in hw_dict.items():
            powers = data.get('Power', {})
            for k, v in powers.items():
                if v is not None and "Package" in k:
                    total_w += float(v)
        return total_w
    except Exception:
        return 0.0

def read_power() -> float:
    if _HAS_HARDWARE_MONITOR and _HM:
        p_cpu = _get_dict_total_power(_HM.cpu)
        p_gpu = _get_dict_total_power(_HM.gpu)
        return p_cpu + p_gpu
    return 0.0

# ──────────────────────────────────────────────
# Global State & Polling
# ──────────────────────────────────────────────
MAX_POINTS = 900  # 30 Minutes
cpu_history = deque([0]*MAX_POINTS, maxlen=MAX_POINTS)
gpu_history = deque([0]*MAX_POINTS, maxlen=MAX_POINTS)
power_history = deque([0]*MAX_POINTS, maxlen=MAX_POINTS)

total_energy_kwh = 0.0

current_stats = {
    "cpu_temp": 0.0,
    "gpu_temp": 0.0,
    "cpu_usage": 0.0,
    "ram_usage": 0.0,
    "sys_power": 0.0,
    "total_kwh": total_energy_kwh
}

def data_poller():
    global total_energy_kwh
    psutil.cpu_percent(interval=None)
    last_time = time.time()
    
    while True:
        try:
            if _HAS_HARDWARE_MONITOR and _HM:
                try:
                    _HM._update_monitor()
                except Exception:
                    pass
                    
            c_temp = read_cpu_temp()
            g_temp = read_gpu_temp()
            
            cpu_pct = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory()
            p_w = read_power()
            
            now = time.time()
            dt = now - last_time
            last_time = now
            
            if p_w > 0:
                joules = p_w * dt
                total_energy_kwh += (joules / 3600000.0)
            
            current_stats.update({
                "cpu_temp": round(c_temp, 1),
                "gpu_temp": round(g_temp, 1),
                "cpu_usage": round(cpu_pct, 1),
                "ram_usage": round(ram.percent, 1),
                "sys_power": round(p_w, 1),
                "total_kwh": total_energy_kwh
            })
            
            cpu_history.append(current_stats["cpu_temp"])
            gpu_history.append(current_stats["gpu_temp"])
            power_history.append(current_stats["sys_power"])
        except Exception as e:
            print(f"Poller error: {e}")
            
        time.sleep(2)

# ──────────────────────────────────────────────
# Mini Overlay Class
# ──────────────────────────────────────────────
class MiniOverlay(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("ThermoLens Mini")
        
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.9)
        
        self.bind("<ButtonPress-1>", self.start_move)
        self.bind("<ButtonRelease-1>", self.stop_move)
        self.bind("<B1-Motion>", self.do_move)
        
        self.frame = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray90", "#0f172a"))
        self.frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        font = ("Segoe UI", 12, "bold")
        self.cpu_lbl = ctk.CTkLabel(self.frame, text="CPU: --°C", font=font, text_color="#06b6d4")
        self.cpu_lbl.pack(side="left", padx=8, pady=4)
        
        self.gpu_lbl = ctk.CTkLabel(self.frame, text="GPU: --°C", font=font, text_color="#f97316")
        self.gpu_lbl.pack(side="left", padx=8, pady=4)
        
        self.pwr_lbl = ctk.CTkLabel(self.frame, text="PWR: --W", font=font, text_color="#ef4444")
        self.pwr_lbl.pack(side="left", padx=8, pady=4)
        
        expand_btn = ctk.CTkButton(self.frame, text="⤢", width=24, height=24, fg_color="transparent", hover_color=("#e2e8f0", "#1e293b"), text_color=("black", "white"), command=self.close_mini)
        expand_btn.pack(side="right", padx=4, pady=4)
        
        self.x = None
        self.y = None
        
    def start_move(self, event):
        self.x = event.x
        self.y = event.y
        
    def stop_move(self, event):
        self.x = None
        self.y = None
        
    def do_move(self, event):
        if self.x is not None and self.y is not None:
            deltax = event.x - self.x
            deltay = event.y - self.y
            x = self.winfo_x() + deltax
            y = self.winfo_y() + deltay
            self.geometry(f"+{x}+{y}")
            
    def close_mini(self):
        self.parent.mini_overlay = None
        self.parent.show_window()
        self.destroy()
        
    def update_data(self, cpu, gpu, pwr):
        self.cpu_lbl.configure(text=f"CPU: {cpu:.0f}°C")
        self.gpu_lbl.configure(text=f"GPU: {gpu:.0f}°C")
        self.pwr_lbl.configure(text=f"PWR: {pwr:.0f}W")

# ──────────────────────────────────────────────
# GUI App
# ──────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ThermoLensGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.mini_overlay = None
        self.title("ThermoLens")
        self.geometry("700x750")
        self.resizable(False, False)
        
        if platform.system() == "Windows":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("thermolens.app.v1")
            except Exception:
                pass
                
        try:
            self.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass
        
        self.withdraw()
        self.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        self.configure(fg_color=("gray95", "#0a0e1a"))
        
        # Main Frame (non-scrollable to save memory & widgets since window is fixed 700x750)
        self.scroll_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True)
        
        # Header
        header = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=12)
        
        title = ctk.CTkLabel(header, text="ThermoLens", font=("Segoe UI", 24, "bold"), text_color=("black", "white"))
        title.pack(side="left")
        
        self.history_period = 600 # default 20m
        def change_history_period(choice):
            mapping = {"1 Min": 30, "5 Min": 150, "15 Min": 450, "20 Min": 600, "30 Min": 900}
            self.history_period = mapping.get(choice, 600)
            
        history_menu = ctk.CTkOptionMenu(header, values=["1 Min", "5 Min", "15 Min", "20 Min", "30 Min"], command=change_history_period, width=90)
        history_menu.set("20 Min")
        history_menu.pack(side="right", padx=10)
        
        def toggle_theme():
            if theme_switch.get() == 1:
                ctk.set_appearance_mode("Light")
            else:
                ctk.set_appearance_mode("Dark")
                
        theme_switch = ctk.CTkSwitch(header, text="Light Mode", command=toggle_theme, width=40)
        theme_switch.pack(side="right", padx=10)
        
        mini_btn = ctk.CTkButton(header, text="Mini Mode", width=70, command=self.show_mini)
        mini_btn.pack(side="right", padx=10)
        
        if DEMO_MODE:
            demo_badge = ctk.CTkLabel(header, text="DEMO MODE", fg_color="#f59e0b", text_color="black", corner_radius=4, padx=8)
            demo_badge.pack(side="right")
        
        # Stat Cards (3x2 Grid)
        grid = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=6)
        grid.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.cpu_card = self.create_stat_card(grid, "CPU Temp", "°C", "#06b6d4", 0, 0)
        self.gpu_card = self.create_stat_card(grid, "GPU Temp", "°C", "#f97316", 0, 1)
        self.power_card = self.create_stat_card(grid, "Sys Power", "W", "#ef4444", 0, 2)
        
        self.usage_card = self.create_stat_card(grid, "CPU Usage", "%", "#8b5cf6", 1, 0)
        self.ram_card = self.create_stat_card(grid, "RAM Usage", "%", "#10b981", 1, 1)
        self.energy_card = self.create_stat_card(grid, "Energy", "kWh", "#eab308", 1, 2)
        
        # Charts
        self.cpu_canvas = self.create_chart_section("CPU History (Last 5m)", "#06b6d4", cpu_history, "°C")
        self.gpu_canvas = self.create_chart_section("GPU History (Last 5m)", "#f97316", gpu_history, "°C")
        self.power_canvas = self.create_chart_section("System Power (Last 5m)", "#ef4444", power_history, "W")
        
        # Footer
        sys_info = get_system_info()
        footer = ctk.CTkLabel(self.scroll_frame, text=sys_info, font=("Segoe UI", 10), text_color=("gray40", "#475569"))
        footer.pack(side="bottom", pady=10)
        
        # Start UI updates
        self.update_ui()
        
    def create_stat_card(self, parent, title, unit, color, row, col):
        card = ctk.CTkFrame(parent, fg_color=("white", "#0f172a"), corner_radius=10)
        card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
        
        lbl_title = ctk.CTkLabel(card, text=title, font=("Segoe UI", 12), text_color=("gray40", "#94a3b8"))
        lbl_title.pack(anchor="w", padx=15, pady=(15, 0))
        
        val_frame = ctk.CTkFrame(card, fg_color="transparent")
        val_frame.pack(anchor="w", padx=15, pady=(5, 15))
        
        lbl_val = ctk.CTkLabel(val_frame, text="--", font=("Segoe UI", 28, "bold"), text_color=("black", "white"))
        lbl_val.pack(side="left")
        
        lbl_unit = ctk.CTkLabel(val_frame, text=unit, font=("Segoe UI", 14), text_color=color)
        lbl_unit.pack(side="left", padx=(5, 0), pady=(8, 0))
        
        return lbl_val

    def create_chart_section(self, title, color, data_source, unit="°C"):
        frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=6)
        
        lbl = ctk.CTkLabel(frame, text=title, font=("Segoe UI", 12, "bold"), text_color=("black", "#e2e8f0"))
        lbl.pack(anchor="w")
        
        canvas = ctk.CTkCanvas(frame, height=110, highlightthickness=0)
        canvas.pack(fill="x", pady=(3, 0))
        
        canvas._data_source = data_source
        canvas._color = color
        canvas._unit = unit
        canvas._cursor_x = None
        canvas._cached_data = []
        
        def on_motion(event):
            canvas._cursor_x = event.x
            self.update_cursor(canvas)
            
        def on_leave(event):
            canvas._cursor_x = None
            self.update_cursor(canvas)
            
        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Leave>", on_leave)
        
        return canvas

    def draw_chart(self, canvas, data, color, max_points):
        if not data:
            return
            
        is_light = ctk.get_appearance_mode() == "Light"
        bg_color = "white" if is_light else "#0f172a"
        grid_color = "#e2e8f0" if is_light else "#1e293b"
        cursor_color = "#94a3b8" if is_light else "#64748b"
        tooltip_bg = "white" if is_light else "#1e293b"
        tooltip_border = "#cbd5e1" if is_light else "#334155"
        tooltip_text_color = "black" if is_light else "white"
        
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10 or h < 10:
            return
            
        # Initialize persistent items if needed, or if canvas resized
        if not getattr(canvas, '_initialized', False) or getattr(canvas, '_init_w', 0) != w or getattr(canvas, '_init_h', 0) != h:
            canvas.delete("all")
            canvas.configure(bg=bg_color)
            canvas._grid_line = canvas.create_line(0, h-1, w, h-1, fill=grid_color)
            canvas._data_line = canvas.create_line(0, 0, 0, 0, fill=color, width=2, smooth=False)
            canvas._cursor_line = canvas.create_line(0, 0, 0, 0, fill=cursor_color, dash=(4, 4), state="hidden")
            canvas._cursor_dot = canvas.create_oval(0, 0, 0, 0, fill=color, outline=bg_color, state="hidden")
            canvas._tooltip_rect = canvas.create_rectangle(0, 0, 0, 0, fill=tooltip_bg, outline=tooltip_border, state="hidden")
            canvas._tooltip_text = canvas.create_text(0, 0, text="", fill=tooltip_text_color, font=("Segoe UI", 10), state="hidden")
            canvas._initialized = True
            canvas._init_w = w
            canvas._init_h = h
            canvas._theme = ctk.get_appearance_mode()
        elif getattr(canvas, '_theme', None) != ctk.get_appearance_mode():
            canvas.configure(bg=bg_color)
            canvas.itemconfig(canvas._grid_line, fill=grid_color)
            canvas.itemconfig(canvas._cursor_line, fill=cursor_color)
            canvas.itemconfig(canvas._cursor_dot, outline=bg_color)
            canvas.itemconfig(canvas._tooltip_rect, fill=tooltip_bg, outline=tooltip_border)
            canvas.itemconfig(canvas._tooltip_text, fill=tooltip_text_color)
            canvas._theme = ctk.get_appearance_mode()
            
        max_val = max(100, max(data) + 10)
        
        # Calculate coordinates for data line
        points = []
        data_len = len(data)
        stride = 1
        if data_len > w:
            stride = max(1, data_len // w)
            
        for i in range(0, data_len, stride):
            x = (i / max(1, max_points - 1)) * w
            y = h - (data[i] / max_val) * h
            points.append(x)
            points.append(y)
            
        if stride > 1 and (data_len - 1) % stride != 0:
            x = w
            y = h - (data[-1] / max_val) * h
            points.append(x)
            points.append(y)
            
        if len(points) >= 4:
            canvas.coords(canvas._data_line, *points)
            canvas.itemconfig(canvas._data_line, state="normal")
        else:
            canvas.itemconfig(canvas._data_line, state="hidden")

    def update_cursor(self, canvas):
        cx = getattr(canvas, '_cursor_x', None)
        data = getattr(canvas, '_cached_data', None)
        
        if not getattr(canvas, '_initialized', False):
            return
            
        if cx is not None and data:
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 10 or h < 10:
                return
                
            max_points = self.history_period
            max_val = max(100, max(data) + 10)
            
            if cx < 0:
                cx = 0
            if cx > w:
                cx = w
            
            canvas.coords(canvas._cursor_line, cx, 0, cx, h)
            canvas.itemconfig(canvas._cursor_line, state="normal")
            
            idx = int(round((cx / w) * max(1, max_points - 1)))
            if 0 <= idx < len(data):
                val = data[idx]
                cy = h - (val / max_val) * h
                
                canvas.coords(canvas._cursor_dot, cx-3, cy-3, cx+3, cy+3)
                canvas.itemconfig(canvas._cursor_dot, state="normal")
                
                text = f"{val:.1f}{getattr(canvas, '_unit', '°C')}"
                tw = 45
                th = 20
                tx = cx - tw/2
                ty = cy - th - 8
                if tx < 0:
                    tx = 0
                if tx + tw > w:
                    tx = w - tw
                if ty < 0:
                    ty = cy + 8
                
                canvas.coords(canvas._tooltip_rect, tx, ty, tx+tw, ty+th)
                canvas.itemconfig(canvas._tooltip_rect, state="normal")
                
                canvas.coords(canvas._tooltip_text, tx+tw/2, ty+th/2)
                canvas.itemconfig(canvas._tooltip_text, text=text, state="normal")
            else:
                canvas.itemconfig(canvas._cursor_dot, state="hidden")
                canvas.itemconfig(canvas._tooltip_rect, state="hidden")
                canvas.itemconfig(canvas._tooltip_text, state="hidden")
        else:
            canvas.itemconfig(canvas._cursor_line, state="hidden")
            canvas.itemconfig(canvas._cursor_dot, state="hidden")
            canvas.itemconfig(canvas._tooltip_rect, state="hidden")
            canvas.itemconfig(canvas._tooltip_text, state="hidden")

    def update_ui(self):
        if self.mini_overlay and self.mini_overlay.winfo_exists():
            self.mini_overlay.update_data(current_stats['cpu_temp'], current_stats['gpu_temp'], current_stats['sys_power'])
            
        if self.state() == "normal":
            self.cpu_card.configure(text=f"{current_stats['cpu_temp']:.1f}")
            self.gpu_card.configure(text=f"{current_stats['gpu_temp']:.1f}")
            self.power_card.configure(text=f"{current_stats['sys_power']:.1f}")
            self.usage_card.configure(text=f"{current_stats['cpu_usage']:.1f}")
            self.ram_card.configure(text=f"{current_stats['ram_usage']:.1f}")
            
            kwh = current_stats['total_kwh']
            if kwh < 1.0:
                self.energy_card.configure(text=f"{kwh:.4f}")
            else:
                self.energy_card.configure(text=f"{kwh:.2f}")
            
            self.cpu_canvas._cached_data = list(cpu_history)[-self.history_period:] if len(cpu_history) > self.history_period else list(cpu_history)
            self.gpu_canvas._cached_data = list(gpu_history)[-self.history_period:] if len(gpu_history) > self.history_period else list(gpu_history)
            self.power_canvas._cached_data = list(power_history)[-self.history_period:] if len(power_history) > self.history_period else list(power_history)
            
            self.draw_chart(self.cpu_canvas, self.cpu_canvas._cached_data, "#06b6d4", self.history_period)
            self.draw_chart(self.gpu_canvas, self.gpu_canvas._cached_data, "#f97316", self.history_period)
            self.draw_chart(self.power_canvas, self.power_canvas._cached_data, "#ef4444", self.history_period)
            
            self.update_cursor(self.cpu_canvas)
            self.update_cursor(self.gpu_canvas)
            self.update_cursor(self.power_canvas)
        
        self.after(2000, self.update_ui)
        
    def hide_window(self):
        self.withdraw()
        
    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def show_mini(self):
        self.withdraw()
        if self.mini_overlay is None or not self.mini_overlay.winfo_exists():
            self.mini_overlay = MiniOverlay(self)

# ──────────────────────────────────────────────
# System Tray Setup
# ──────────────────────────────────────────────
def setup_tray(app_instance):
    def on_show(icon, item):
        app_instance.after(0, app_instance.show_window)
        
    def on_exit(icon, item):
        icon.stop()
        app_instance.after(0, app_instance.quit)
        
    menu = pystray.Menu(
        pystray.MenuItem('Show Dashboard', on_show, default=True),
        pystray.MenuItem('Show Mini Overlay', lambda icon, item: app_instance.after(0, app_instance.show_mini)),
        pystray.MenuItem('Exit ThermoLens', on_exit)
    )
    
    try:
        tray_image = Image.open(resource_path("icon.ico"))
    except Exception:
        tray_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        
    icon = pystray.Icon("ThermoLens", tray_image, "ThermoLens", menu)
    icon.run()

if __name__ == "__main__":
    t_poller = threading.Thread(target=data_poller, daemon=True)
    t_poller.start()
    
    app = ThermoLensGUI()
    
    t_tray = threading.Thread(target=setup_tray, args=(app,), daemon=True)
    t_tray.start()
    
    app.after(500, app.show_window)
    app.mainloop()
