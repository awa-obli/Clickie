import os
import sys
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Listener as KeyboardListener, Key

import pywinstyles
import darkdetect
import sv_ttk

class AutoClickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Clickie 连点器 - V1.2.0")
        self.root.resizable(False, False)

        self.mouse = MouseController()
        self.clicking = False
        self.waiting = False
        self.wait_after_id = None
        self.click_thread = None
        self.click_count = 0

        self._loading = False

        self._build_ui()
        self._load_settings()
        # 加载的热键可能不同于默认 F6，刷新按钮文字
        self._update_button_text()
        self._start_hotkey_listener()

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}
        # Combobox 输入框字体特殊处理
        self.default_font = ("Microsoft YaHei", 10)

        frame = ttk.Frame(self.root, padding=15)
        frame.grid(row=0, column=0)

        # 点击间隔
        ttk.Label(frame, text="点击间隔 (毫秒):").grid(row=0, column=0, sticky="w", **pad)
        self.interval_var = tk.StringVar(value="100")
        self.interval_entry = ttk.Entry(frame, textvariable=self.interval_var, width=12)
        self.interval_entry.grid(row=0, column=1, **pad)

        # 鼠标按键
        ttk.Label(frame, text="鼠标按键:").grid(row=1, column=0, sticky="w", **pad)
        self.button_var = tk.StringVar(value="左键")
        self.button_combo = ttk.Combobox(
            frame, textvariable=self.button_var, values=["左键", "右键"],
            state="readonly", width=8, font=self.default_font
        )
        self.button_combo.grid(row=1, column=1, **pad)

        # 点击模式
        ttk.Label(frame, text="点击模式:").grid(row=2, column=0, sticky="w", **pad)
        self.mode_var = tk.StringVar(value="单击")
        self.mode_combo = ttk.Combobox(
            frame, textvariable=self.mode_var, values=["单击", "双击"],
            state="readonly", width=8, font=self.default_font
        )
        self.mode_combo.grid(row=2, column=1, **pad)

        # 点击次数
        ttk.Label(frame, text="点击次数 (0=无限):").grid(row=3, column=0, sticky="w", **pad)
        self.count_var = tk.StringVar(value="0")
        self.count_entry = ttk.Entry(frame, textvariable=self.count_var, width=12)
        self.count_entry.grid(row=3, column=1, **pad)

        # 热键设置
        ttk.Label(frame, text="热键设置:").grid(row=4, column=0, sticky="w", **pad)
        self.hotkey_var = tk.StringVar(value="F6")
        self.hotkey_var.trace_add("write", self._toggle_hotkey)
        self.hotkey_combo = ttk.Combobox(
            frame, textvariable=self.hotkey_var, values=[f"F{i}" for i in range(1, 13)],
            state="readonly", width=8, font=self.default_font
        )
        self.hotkey_combo.grid(row=4, column=1, **pad)

        # 开始/停止按钮
        self.toggle_btn = ttk.Button(frame, text=f"开始(F6)", command=self._toggle_clicking_via_button)
        self.toggle_btn.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)

        # 状态显示
        self.status_var = tk.StringVar(value="状态: 已停止 | 已点击: 0")
        ttk.Label(frame, textvariable=self.status_var).grid(
            row=6, column=0, columnspan=2, pady=(6, 0)
        )

        # 任一设置改动即自动保存
        for var in (self.interval_var, self.button_var, self.mode_var, self.count_var, self.hotkey_var):
            var.trace_add("write", self._on_settings_changed)

    def _update_button_text(self):
        if self.clicking:
            text = f"停止({self.hotkey_var.get()})"
        elif self.waiting:
            text = f"取消({self.hotkey_var.get()})"
        else:
            text = f"开始({self.hotkey_var.get()})"
        self.toggle_btn.config(text=text)

    def _set_inputs_enabled(self, enabled: bool):
        combo_state = "readonly" if enabled else "disabled"
        entry_state = "normal" if enabled else "disabled"
        self.interval_entry.config(state=entry_state)
        self.button_combo.config(state=combo_state)
        self.mode_combo.config(state=combo_state)
        self.count_entry.config(state=entry_state)
        self.hotkey_combo.config(state=combo_state)

    # ---------------- 设置保存 ----------------
    def _on_settings_changed(self, *args):
        # 加载设置期间不写盘，避免"加载→写回"循环
        if self._loading:
            return
        self._save_settings()

    def _save_settings(self):
        data = {
            "interval": self.interval_var.get(),
            "button": self.button_var.get(),
            "mode": self.mode_var.get(),
            "count": self.count_var.get(),
            "hotkey": self.hotkey_var.get(),
        }
        try:
            os.makedirs(os.path.dirname(self.config_path()), exist_ok=True)
            with open(self.config_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"保存设置失败: {e}")

    def _load_settings(self):
        self._loading = True
        try:
            path = self.config_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return

            # 逐项校验，非法字段只回退该字段默认值
            if self.is_valid_interval(data.get("interval")):
                self.interval_var.set(data["interval"])
            if data.get("button") in ("左键", "右键"):
                self.button_var.set(data["button"])
            if data.get("mode") in ("单击", "双击"):
                self.mode_var.set(data["mode"])
            if self.is_valid_count(data.get("count")):
                self.count_var.set(str(data["count"]))
            if data.get("hotkey") in (f"F{i}" for i in range(1, 13)):
                self.hotkey_var.set(data["hotkey"])
        except (OSError, json.JSONDecodeError) as e:
            print(f"加载设置失败，使用默认值: {e}")
        finally:
            self._loading = False

    def config_path(self):
        """配置文件路径: %APPDATA%\\Clickie\\config.json"""
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Clickie", "config.json")

    # ---------------- 热键 ----------------
    def _toggle_hotkey(self, *args):
        # 加载设置期间由 __init__ 统一启动监听器，避免重复启停
        if self._loading:
            return
        if self.listener.running:
            self.listener.stop()
        self._start_hotkey_listener()

        self._update_button_text()

    def _start_hotkey_listener(self):
        KEY_MAP = {
            "F1": Key.f1,
            "F2": Key.f2,
            "F3": Key.f3,
            "F4": Key.f4,
            "F5": Key.f5,
            "F6": Key.f6,
            "F7": Key.f7,
            "F8": Key.f8,
            "F9": Key.f9,
            "F10": Key.f10,
            "F11": Key.f11,
            "F12": Key.f12,
        }

        target_key = KEY_MAP[self.hotkey_var.get()]

        def on_press(key):
            if key == target_key:
                # 用 after 切回主线程操作 GUI
                self.root.after(0, self._toggle_clicking_via_hotkey)

        self.listener = KeyboardListener(on_press=on_press)
        self.listener.daemon = True
        self.listener.start()

    # ---------------- 点击逻辑 ----------------
    def _toggle_clicking_via_button(self):
        # 按钮专用:启动时走等待流程
        if self.clicking:
            self._stop_clicking()
        elif self.waiting:
            self._cancel_waiting()
        else:
            if not self._validate_inputs():
                return
            self._start_waiting()

    def _toggle_clicking_via_hotkey(self):
        # 热键专用:启动/停止都立即生效
        if self.clicking:
            self._stop_clicking()
        elif self.waiting:
            self._cancel_waiting()
        else:
            if not self._validate_inputs():
                return
            self._start_clicking()

    def _validate_inputs(self):
        # 校验输入
        if not self.is_valid_interval(self.interval_var.get()):
            messagebox.showerror("输入错误", "点击间隔必须是大于0的数字(毫秒)")
            return False

        if not self.is_valid_count(self.count_var.get()):
            messagebox.showerror("输入错误", "点击次数必须是不小于0的整数")
            return False

        return True

    def is_valid_interval(self, value):
        """点击间隔校验"""
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False

    def is_valid_count(self, value):
        """点击次数校验"""
        try:
            return int(value) >= 0
        except (TypeError, ValueError):
            return False

    def _start_waiting(self):
        self._set_inputs_enabled(False)
        self.waiting = True
        self.wait_remaining = 3  # 倒计时秒数
        self._update_button_text()
        self._countdown_tick()

    def _cancel_waiting(self):
        self._set_inputs_enabled(True)
        self.waiting = False
        # 打断计时器
        if self.wait_after_id is not None:
            self.root.after_cancel(self.wait_after_id)
            self.wait_after_id = None
        self._update_button_text()
        self.status_var.set(f"状态: 已停止 | 已点击: {self.click_count}")

    def _countdown_tick(self):
        if self.wait_remaining <= 0:
            self.waiting = False
            self._start_clicking()
            return

        self.status_var.set(f"状态：{self.wait_remaining}秒后开始...")
        self.wait_remaining -= 1
        # 记录 id，方便取消时打断这个计时器
        self.wait_after_id = self.root.after(1000, self._countdown_tick)

    def _start_clicking(self):
        self._set_inputs_enabled(False)
        self.clicking = True
        self.click_count = 0
        self._update_button_text()

        self.click_thread = threading.Thread(target=self._click_loop, daemon=True)
        self.click_thread.start()

    def _stop_clicking(self):
        self._set_inputs_enabled(True)
        self.clicking = False
        self._update_button_text()
        self.status_var.set(f"状态: 已停止 | 已点击: {self.click_count}")

    def _click_loop(self):
        button = Button.left if self.button_var.get() == "左键" else Button.right
        double = self.mode_var.get() == "双击"
        interval_sec = float(self.interval_var.get()) / 1000.0
        max_count = int(self.count_var.get())

        while self.clicking:
            if double:
                self.mouse.click(button, 2)
            else:
                self.mouse.click(button, 1)

            self.click_count += 1
            # 用 after 线程安全地更新状态标签
            # 同时在实际执行时判断是否还在点击状态，避免竞态覆盖状态文本（“已停止”可能会被覆盖成“点击中”）
            self.root.after(0, lambda: self.status_var.set(
                f"状态: 点击中... | 已点击: {self.click_count}"
            ) if self.clicking else None)

            if max_count and self.click_count >= max_count:
                self.root.after(0, self._stop_clicking)
                break

            time.sleep(interval_sec)


def resource_path(relative_path):
    """获取资源文件的绝对路径"""
    try:
        base_path = sys._MEIPASS  # PyInstaller 打包后解压的临时目录
    except AttributeError:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def apply_fonts(root):
    """应用字体"""
    style = ttk.Style()
    default_font = ("Microsoft YaHei", 10)
    for style_name in ("TLabel", "TButton", "TEntry", "TFrame"):
        style.configure(style_name, font=default_font)
    # Combobox 下拉列表字体
    root.option_add("*TCombobox*Listbox.font", default_font)


def apply_theme_to_titlebar(root, theme):
    """根据当前主题，切换标题栏颜色"""
    version = sys.getwindowsversion()

    if version.major == 10 and version.build >= 22000:
        # Windows 11
        pywinstyles.change_header_color(root, "#1c1c1c" if theme == "Dark" else "#fafafa")
    elif version.major == 10:
        # Windows 10
        pywinstyles.apply_style(root, "dark" if theme == "Dark" else "normal")
        root.wm_attributes("-alpha", 0.99)
        root.wm_attributes("-alpha", 1)


def apply_icon_by_theme(root, theme):
    """根据当前主题，切换窗口/任务栏图标。"""
    icon_name = "icon_dark.ico" if theme == "Dark" else "icon_light.ico"
    icon_path = resource_path(os.path.join("assets", icon_name))
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"设置图标失败: {e}")


def apply_full_theme(root, theme):
    # Sun Valley ttk主题
    sv_ttk.set_theme(theme)
    apply_fonts(root)
    apply_theme_to_titlebar(root, theme)
    apply_icon_by_theme(root, theme)


def watch_theme(root, interval_ms=2000):
    """定期检测系统主题是否发生变化，自动刷新 ttk 主题、标题栏颜色和窗口图标"""
    current = getattr(root, "_last_theme", None)
    theme = darkdetect.theme()
    if theme != current:
        root._last_theme = theme
        apply_full_theme(root, theme)
    root.after(interval_ms, watch_theme, root)


def main():
    root = tk.Tk()
    root.withdraw()  # 先隐藏窗口，防止闪烁
    app = AutoClickerApp(root)

    apply_full_theme(root, darkdetect.theme())
    watch_theme(root)

    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
