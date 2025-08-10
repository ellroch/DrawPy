import ctypes
import ctypes.wintypes as wintypes
import win32con
import win32gui
import win32ui
import win32api
import atexit
import threading
import sys
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Constants
WM_HOTKEY = 0x0312
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_MOUSEMOVE = 0x0200
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_KEYUP = 0x0101

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

COLOR_MAP = {
    1: win32api.RGB(255, 0, 0),     # Red
    2: win32api.RGB(0, 255, 0),     # Green
    3: win32api.RGB(0, 0, 255),     # Blue
    4: win32api.RGB(255, 255, 0),   # Yellow
}

# Windows API helpers
user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32


def rgb_to_colorref(rgb):
    # COLORREF is 0x00bbggrr
    r = rgb & 0xFF
    g = (rgb >> 8) & 0xFF
    b = (rgb >> 16) & 0xFF
    return (b << 16) | (g << 8) | r

class DrawOverlay:
    def __init__(self):
        self.hInstance = kernel32.GetModuleHandleW(None)

        self.className = "DrawPyOverlayWindowClass"

        self._register_window_class()
        self.hwnd = self._create_overlay_window()
        print(f"[DEBUG] hwnd: {self.hwnd}")

        self.is_drawing = False
        self.is_draw_mode = False
        self.draw_color_id = 1
        self.draw_color = COLOR_MAP[self.draw_color_id]

        self.stroke_points = []
        self.strokes = []  # list of (color_id, [points])

        self._create_compatible_bitmap()

        self._register_hotkeys()

        self._set_window_clickthrough(True)

        atexit.register(self.cleanup)

        logging.info("drawpy: Activate with Alt+Shift+1..4 to start drawing, hold Alt to keep drawing mode.")
        logging.info("Right-click and drag to draw. Release Alt to exit drawing mode and clear.")
        logging.info("[info] Overlay window created and shown")
        logging.info("[info] Registered hotkeys Alt+Shift+1..4 and Alt+1..4")

    def _register_window_class(self):
        # WNDCLASS structure
        wndclass = win32gui.WNDCLASS()
        wndclass.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wndclass.lpfnWndProc = self._wnd_proc
        wndclass.hInstance = self.hInstance
        wndclass.hCursor = win32gui.LoadCursor(None, win32con.IDC_ARROW)
        wndclass.hbrBackground = win32con.COLOR_WINDOW  # White background
        wndclass.lpszClassName = self.className

        atom = win32gui.RegisterClass(wndclass)
        if not atom:
            raise RuntimeError("Failed to register window class")

    def _create_overlay_window(self):
        # Create layered transparent fullscreen window
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST,
            self.className,
            "DrawPy Overlay",
            win32con.WS_POPUP,
            0,
            0,
            screen_w,
            screen_h,
            None,
            None,
            self.hInstance,
            None,
        )
        
        if not hwnd:
            raise RuntimeError("Failed to create overlay window")

        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.UpdateWindow(hwnd)

        # Set layered window attributes (fully transparent initially)
        win32gui.SetLayeredWindowAttributes(hwnd, 0, 0, win32con.LWA_ALPHA)

        return hwnd

    def _create_compatible_bitmap(self):
        # Create memory DC and bitmap for drawing buffer
        hdc_screen = win32gui.GetDC(0)
        self.memdc = win32gui.CreateCompatibleDC(hdc_screen)
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        self.bitmap = win32gui.CreateCompatibleBitmap(hdc_screen, screen_w, screen_h)
        win32gui.SelectObject(self.memdc, self.bitmap)
        win32gui.ReleaseDC(0, hdc_screen)

        # Fill bitmap with transparent black
        brush = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        rect = (0, 0, screen_w, screen_h)
        win32gui.FillRect(self.memdc, rect, brush)

    def _register_hotkeys(self):
        for id_, (mod, vk) in HOTKEY_IDS.items():
            if not user32.RegisterHotKey(self.hwnd, id_, mod, vk):
                raise RuntimeError(f"Failed to register hotkey id={id_} mod={mod} vk={vk}")

    def _unregister_hotkeys(self):
        for id_ in HOTKEY_IDS.keys():
            user32.UnregisterHotKey(self.hwnd, id_)

    def _set_window_clickthrough(self, clickthrough: bool):
        # Toggle WS_EX_TRANSPARENT for click-through when not drawing
        exstyle = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        if clickthrough:
            exstyle |= win32con.WS_EX_TRANSPARENT
        else:
            exstyle &= ~win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, exstyle)
        # Update layered attributes to opaque or transparent
        if clickthrough:
            win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 0, win32con.LWA_ALPHA)
        else:
            win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 255, win32con.LWA_ALPHA)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            self._on_hotkey(wparam)
            return 0

        elif msg == WM_PAINT:
            self._on_paint()
            return 0

        elif msg == WM_RBUTTONDOWN:
            if self.is_draw_mode:
                self.is_drawing = True
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                self.stroke_points = [(x, y)]
                logging.info("[info] Started drawing stroke")
                return 0  # Capture event (don't pass to others)
            else:
                # Pass through when not drawing
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        elif msg == WM_MOUSEMOVE:
            if self.is_draw_mode and self.is_drawing:
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                last_point = self.stroke_points[-1]
                self.stroke_points.append((x, y))
                logging.debug(f"[debug] Drawing line at {last_point} to {(x, y)} with color {self.draw_color_id}")
                # Draw line segment on memdc
                self._draw_line(last_point, (x, y), self.draw_color)
                self._invalidate()
                return 0  # Capture event

            else:
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        elif msg == WM_RBUTTONUP:
            if self.is_draw_mode and self.is_drawing:
                self.is_drawing = False
                self.strokes.append((self.draw_color_id, list(self.stroke_points)))
                self.stroke_points.clear()
                logging.info("[info] Ended drawing stroke")
                return 0  # Capture event
            else:
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        elif msg == WM_KEYUP:
            if wparam == win32con.VK_MENU:  # ALT released
                if self.is_draw_mode:
                    self._exit_draw_mode()
                return 0

            else:
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        elif msg == WM_DESTROY:
            self._unregister_hotkeys()
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_hotkey(self, hotkey_id):
        # Alt+Shift+1..4 or Alt+1..4 triggers enter draw mode or color change
        if hotkey_id in HOTKEY_IDS:
            mod, vk = HOTKEY_IDS[hotkey_id]
            color_num = vk - ord('0')
            # If Shift pressed, enter draw mode with color; else just change color if in draw mode
            if mod & MOD_SHIFT:
                self._enter_draw_mode(color_num)
            else:
                if self.is_draw_mode:
                    self._change_draw_color(color_num)
            logging.info(f"[info] Hotkey pressed id={hotkey_id}")
            return True
        return False

    def _enter_draw_mode(self, color_num):
        if not self.is_draw_mode:
            self.is_draw_mode = True
            self._change_draw_color(color_num)
            self._set_window_clickthrough(False)  # capture mouse
            logging.info(f"[info] Enter draw mode with color {color_num}")
        else:
            self._change_draw_color(color_num)

    def _change_draw_color(self, color_num):
        if color_num in COLOR_MAP:
            self.draw_color_id = color_num
            self.draw_color = COLOR_MAP[color_num]
            logging.info(f"[info] Changed draw color to {color_num}")

    def _exit_draw_mode(self):
        self.is_draw_mode = False
        self.is_drawing = False
        self.stroke_points.clear()
        self.strokes.clear()
        self._clear_bitmap()
        self._set_window_clickthrough(True)  # allow clicks through window
        self._invalidate()
        logging.info("[info] Alt released, exit draw mode")

    def _clear_bitmap(self):
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        brush = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        rect = (0, 0, screen_w, screen_h)
        win32gui.FillRect(self.memdc, rect, brush)

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
            return  # Failed to get HDC, just return

        # BitBlt from memdc bitmap to window DC
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        win32gui.BitBlt(hdc, 0, 0, screen_w, screen_h, self.memdc, 0, 0, win32con.SRCCOPY)

        user32.EndPaint(self.hwnd, ctypes.byref(ps))


    def run(self):
        # Message loop
        msg = wintypes.MSG()
        while True:
            bRet = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if bRet == 0:
                break
            elif bRet == -1:
                logging.error("GetMessage error")
                break
            else:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

    def cleanup(self):
        self._unregister_hotkeys()
        win32gui.DestroyWindow(self.hwnd)
        logging.info("[info] Cleanup done")


if __name__ == "__main__":
    app = DrawOverlay()
    app.run()
