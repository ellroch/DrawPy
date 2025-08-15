import ctypes
import ctypes.wintypes as wintypes
import win32con
import win32gui
import win32ui
import win32api
import atexit
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# ==========================
# CONFIGURABLE GLOBALS
# ==========================
BACKGROUND_COLOR = win32api.RGB(0, 0, 0)   # background fill color (behind strokes)
BACKGROUND_ALPHA_PERCENT = 40              # background transparency (0 = fully transparent, 100 = fully opaque)

COLOR_MAP = {
    1: win32api.RGB(255, 0, 0),     # Red
    2: win32api.RGB(0, 255, 0),     # Green
    3: win32api.RGB(0, 0, 255),     # Blue
    4: win32api.RGB(255, 255, 0),   # Yellow
}
# ==========================

# Constants
WM_HOTKEY = 0x0312
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_KEYUP = 0x0101
WM_ERASEBKGND = 0x0014

MOD_ALT = 0x0001
MOD_SHIFT = 0x0004

# Define PAINTSTRUCT struct for ctypes
class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32)
    ]

HOTKEY_IDS = {
    # Hotkey ID : (modifiers, vk)
    101: (MOD_ALT | MOD_SHIFT, ord('1')),
    102: (MOD_ALT, ord('1')),
    103: (MOD_ALT | MOD_SHIFT, ord('2')),
    104: (MOD_ALT, ord('2')),
    105: (MOD_ALT | MOD_SHIFT, ord('3')),
    106: (MOD_ALT, ord('3')),
    107: (MOD_ALT | MOD_SHIFT, ord('4')),
    108: (MOD_ALT, ord('4')),
}

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.windll.kernel32


class DrawOverlay:
    def __init__(self):
        self.hInstance = kernel32.GetModuleHandleW(None)
        self.className = "DrawPyOverlayWindowClass"

        self.is_drawing = False
        self.is_draw_mode = False
        self.draw_color_id = 1
        self.draw_color = COLOR_MAP[self.draw_color_id]

        self.stroke_points = []
        self.strokes = []  # list of (color_id, [points]) for persistent (right-click) strokes
        self.drawing_button = None  # 'L' or 'R' while a stroke is in progress

        self.hwnd = None
        self.memdc = None
        self.bitmap = None

        self._register_window_class()
        self._create_overlay_window(show=False)
        self._create_compatible_bitmap()
        self._register_hotkeys()

        self._set_window_clickthrough(True)  # Start as click-through & transparent

        atexit.register(self.cleanup)

        logging.info("drawpy: Activate with Alt+Shift+1..4 to start drawing, hold Alt to keep drawing mode.")
        logging.info("Right-click and drag = persistent stroke. Left-click and drag = temporary stroke (erases on release).")
        logging.info("Release Alt to clear and exit drawing mode.")
        logging.info("[info] Overlay window created but hidden")
        logging.info("[info] Registered hotkeys Alt+Shift+1..4 and Alt+1..4")

    def _register_window_class(self):
        wndclass = win32gui.WNDCLASS()
        wndclass.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW | win32con.CS_DBLCLKS
        wndclass.lpfnWndProc = self._wnd_proc
        wndclass.hInstance = self.hInstance
        wndclass.hCursor = win32gui.LoadCursor(None, win32con.IDC_ARROW)
        wndclass.hbrBackground = 0
        wndclass.lpszClassName = self.className
        atom = win32gui.RegisterClass(wndclass)
        if not atom:
            raise RuntimeError("Failed to register window class")

    def _create_overlay_window(self, show=True):
        vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        vw = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        vh = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

        exstyle = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | 0x02000000  # WS_EX_COMPOSITED
        )

        hwnd = win32gui.CreateWindowEx(
            exstyle,
            self.className,
            "DrawPy Overlay",
            win32con.WS_POPUP,
            vx,
            vy,
            vw,
            vh,
            None,
            None,
            self.hInstance,
            None,
        )

        if not hwnd:
            raise RuntimeError("Failed to create overlay window")

        self.hwnd = hwnd
        if show:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.UpdateWindow(hwnd)
            alpha_val = int(255 * (BACKGROUND_ALPHA_PERCENT / 100))
            win32gui.SetLayeredWindowAttributes(hwnd, 0, alpha_val, win32con.LWA_ALPHA)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    def _create_compatible_bitmap(self):
        vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        vw = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        vh = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

        hdc_screen = win32gui.GetDC(0)
        self.memdc = win32gui.CreateCompatibleDC(hdc_screen)
        self.bitmap = win32gui.CreateCompatibleBitmap(hdc_screen, vw, vh)
        win32gui.SelectObject(self.memdc, self.bitmap)
        win32gui.ReleaseDC(0, hdc_screen)

        self._clear_bitmap()

    def _register_hotkeys(self):
        for id_, (mod, vk) in HOTKEY_IDS.items():
            if not user32.RegisterHotKey(self.hwnd, id_, mod, vk):
                raise RuntimeError(f"Failed to register hotkey id={id_} mod={mod} vk={vk}")

    def _unregister_hotkeys(self):
        for id_ in HOTKEY_IDS.keys():
            user32.UnregisterHotKey(self.hwnd, id_)

    def _set_window_clickthrough(self, clickthrough: bool):
        exstyle = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        if clickthrough:
            exstyle |= win32con.WS_EX_TRANSPARENT
        else:
            exstyle &= ~win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, exstyle)

        alpha_val = int(255 * (BACKGROUND_ALPHA_PERCENT / 100))
        if clickthrough:
            # idle: fully transparent & pass-through
            win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 0, win32con.LWA_ALPHA)
        else:
            # drawing: semi-transparent background with opaque strokes
            win32gui.SetLayeredWindowAttributes(self.hwnd, 0, alpha_val, win32con.LWA_ALPHA)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            self._on_hotkey(wparam)
            return 0

        elif msg == WM_PAINT:
            self._on_paint()
            return 0

        elif msg == WM_ERASEBKGND:
            return 1

        # ----- Right-click: persistent stroke -----
        elif msg == WM_RBUTTONDOWN:
            if self.is_draw_mode:
                self.is_drawing = True
                self.drawing_button = 'R'
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                self.stroke_points = [(x, y)]
                return 0

        elif msg == WM_RBUTTONUP:
            if self.is_draw_mode and self.is_drawing and self.drawing_button == 'R':
                self.is_drawing = False
                # persist this stroke
                self.strokes.append((self.draw_color_id, list(self.stroke_points)))
                self.stroke_points.clear()
                self.drawing_button = None
                return 0

        # ----- Left-click: temporary stroke (erase on release) -----
        elif msg == WM_LBUTTONDOWN:
            if self.is_draw_mode:
                self.is_drawing = True
                self.drawing_button = 'L'
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                self.stroke_points = [(x, y)]
                return 0

        elif msg == WM_LBUTTONUP:
            if self.is_draw_mode and self.is_drawing and self.drawing_button == 'L':
                self.is_drawing = False
                # do NOT persist this stroke; rebuild canvas from persistent strokes
                self.stroke_points.clear()
                self.drawing_button = None
                self._redraw_all()
                self._invalidate()
                return 0

        elif msg == WM_MOUSEMOVE:
            if self.is_draw_mode and self.is_drawing:
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                last_point = self.stroke_points[-1]
                self.stroke_points.append((x, y))
                self._draw_line(last_point, (x, y), self.draw_color)
                self._invalidate()
                return 0

        elif msg == WM_KEYUP:
            if wparam == win32con.VK_MENU:  # ALT released
                if self.is_draw_mode:
                    self._exit_draw_mode()
                return 0

        elif msg == WM_DESTROY:
            self._unregister_hotkeys()
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_hotkey(self, hotkey_id):
        if hotkey_id in HOTKEY_IDS:
            mod, vk = HOTKEY_IDS[hotkey_id]
            color_num = vk - ord('0')
            if mod & MOD_SHIFT:
                self._enter_draw_mode(color_num)
            else:
                if self.is_draw_mode:
                    self._change_draw_color(color_num)
            return True
        return False

    def _enter_draw_mode(self, color_num):
        if not self.is_draw_mode:
            self.is_draw_mode = True
            self._change_draw_color(color_num)
            self._set_window_clickthrough(False)
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.UpdateWindow(self.hwnd)
        else:
            self._change_draw_color(color_num)

    def _change_draw_color(self, color_num):
        if color_num in COLOR_MAP:
            self.draw_color_id = color_num
            self.draw_color = COLOR_MAP[color_num]

    def _exit_draw_mode(self):
        self.is_draw_mode = False
        self.is_drawing = False
        self.drawing_button = None
        self.stroke_points.clear()
        self.strokes.clear()          # clear persistent strokes
        self._clear_bitmap()          # wipe canvas
        self._set_window_clickthrough(True)
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        self._invalidate()

    def _clear_bitmap(self):
        vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        vw = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        vh = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        brush = win32gui.CreateSolidBrush(BACKGROUND_COLOR)
        rect = (0, 0, vw, vh)
        win32gui.FillRect(self.memdc, rect, brush)
        win32gui.DeleteObject(brush)

    def _redraw_all(self):
        """Clear to background and redraw all persistent strokes."""
        self._clear_bitmap()
        for color_id, points in self.strokes:
            color = COLOR_MAP.get(color_id, self.draw_color)
            for i in range(1, len(points)):
                self._draw_line(points[i-1], points[i], color)

    def _draw_line(self, pt1, pt2, color):
        pen = win32gui.CreatePen(win32con.PS_SOLID, 4, color)
        old_pen = win32gui.SelectObject(self.memdc, pen)
        win32gui.MoveToEx(self.memdc, pt1[0], pt1[1])
        win32gui.LineTo(self.memdc, pt2[0], pt2[1])
        win32gui.SelectObject(self.memdc, old_pen)
        win32gui.DeleteObject(pen)

    def _invalidate(self):
        win32gui.InvalidateRect(self.hwnd, None, True)

    def _on_paint(self):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        if not hdc:
            return
        vw = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        vh = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        win32gui.BitBlt(hdc, 0, 0, vw, vh, self.memdc, 0, 0, win32con.SRCCOPY)
        user32.EndPaint(self.hwnd, ctypes.byref(ps))

    def run(self):
        msg = wintypes.MSG()
        while True:
            bRet = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if bRet == 0:
                break
            elif bRet == -1:
                break
            else:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

    def cleanup(self):
        self._unregister_hotkeys()
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)


if __name__ == "__main__":
    app = DrawOverlay()
    app.run()
