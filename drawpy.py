import ctypes
import ctypes.wintypes as wintypes
import win32con
import win32gui
import win32ui
import win32api
import atexit
import logging
import struct

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Constants
WM_HOTKEY = 0x0312
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_MOUSEMOVE = 0x0200
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

COLOR_MAP = {
    1: win32api.RGB(255, 0, 0),     # Red
    2: win32api.RGB(0, 255, 0),     # Green
    3: win32api.RGB(0, 0, 255),     # Blue
    4: win32api.RGB(255, 255, 0),   # Yellow
}

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)

# Define CreateDIBSection prototype
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(ctypes.c_byte),  # pointer to BITMAPINFO
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),  # pointer to pointer to bits
    wintypes.HANDLE,
    wintypes.DWORD
]

AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

class DrawOverlay:
    def __init__(self):
        self.hInstance = kernel32.GetModuleHandleW(None)
        self.className = "DrawPyOverlayWindowClass"

        self.is_drawing = False
        self.is_draw_mode = False
        self.draw_color_id = 1
        self.draw_color = COLOR_MAP[self.draw_color_id]

        self.stroke_points = []
        self.strokes = []  # list of (color_id, [points])

        self.hwnd = None
        self.memdc = None
        self.bitmap = None

        self._register_window_class()

        # Create window hidden at start (to allow hotkey registration)
        self._create_overlay_window(show=False)
        self._create_compatible_bitmap()

        self._register_hotkeys()

        self._set_window_clickthrough(True)  # Start as click-through & transparent

        atexit.register(self.cleanup)

        logging.info("drawpy: Activate with Alt+Shift+1..4 to start drawing, hold Alt to keep drawing mode.")
        logging.info("Right-click and drag to draw. Release Alt to exit drawing mode and clear.")
        logging.info("[info] Overlay window created but hidden")
        logging.info("[info] Registered hotkeys Alt+Shift+1..4 and Alt+1..4")

    def _register_window_class(self):
        wndclass = win32gui.WNDCLASS()
        wndclass.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW | win32con.CS_DBLCLKS
        wndclass.lpfnWndProc = self._wnd_proc
        wndclass.hInstance = self.hInstance
        wndclass.hCursor = win32gui.LoadCursor(None, win32con.IDC_ARROW)
        wndclass.hbrBackground = 0  # No background brush to avoid erase
        wndclass.lpszClassName = self.className
        atom = win32gui.RegisterClass(wndclass)
        if not atom:
            raise RuntimeError("Failed to register window class")

    def _create_overlay_window(self, show=True):
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        # Extended style: layered, transparent (clickthrough), topmost, composited for flicker reduction
        exstyle = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | 0x02000000  # WS_EX_COMPOSITED (not in win32con but value is 0x02000000)
        )

        hwnd = win32gui.CreateWindowEx(
            exstyle,
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

        self.hwnd = hwnd
        if show:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.UpdateWindow(hwnd)
            # Do NOT use SetLayeredWindowAttributes here, UpdateLayeredWindow will control transparency
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    def _create_compatible_bitmap(self):
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        hdc_screen = win32gui.GetDC(0)
        self.memdc = win32gui.CreateCompatibleDC(hdc_screen)

        # Prepare BITMAPINFO header bytes
        bmi = struct.pack(
            '<IiiHHIIIIII',  # little-endian, standard BITMAPINFOHEADER format
            40,          # biSize
            screen_w,    # biWidth
            -screen_h,   # biHeight (negative for top-down)
            1,           # biPlanes
            32,          # biBitCount
            0,           # biCompression (BI_RGB)
            0,           # biSizeImage
            0,           # biXPelsPerMeter
            0,           # biYPelsPerMeter
            0,           # biClrUsed
            0            # biClrImportant
        )

        # Create a ctypes buffer for BITMAPINFO
        bmi_buffer = ctypes.create_string_buffer(bmi)

        bits_ptr = ctypes.c_void_p()
        hbitmap = gdi32.CreateDIBSection(
            hdc_screen,
            ctypes.cast(bmi_buffer, ctypes.POINTER(ctypes.c_byte)),
            win32con.DIB_RGB_COLORS,
            ctypes.byref(bits_ptr),
            None,
            0
        )

        if not hbitmap:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)

        self.bitmap = hbitmap
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
        # Do NOT call SetLayeredWindowAttributes - UpdateLayeredWindow manages alpha

    def _update_layered_window(self):
        hdc_screen = win32gui.GetDC(0)

        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        size = (screen_w, screen_h)
        point_zero = (0, 0)

        # Pass 4-tuple instead of ctypes struct per win32gui.UpdateLayeredWindow expectations
        blend = (AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)  # BlendOp, BlendFlags, SourceConstantAlpha, AlphaFormat

        res = win32gui.UpdateLayeredWindow(
            self.hwnd,
            hdc_screen,
            None,
            size,
            self.memdc,
            point_zero,
            0,
            blend,
            win32con.ULW_ALPHA
        )
        win32gui.ReleaseDC(0, hdc_screen)

        if not res:
            logging.error("UpdateLayeredWindow failed")

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            self._on_hotkey(wparam)
            return 0

        elif msg == WM_PAINT:
            self._on_paint()
            return 0

        elif msg == WM_ERASEBKGND:
            # Prevent background erase to reduce flicker
            return 1

        elif msg == WM_RBUTTONDOWN:
            if self.is_draw_mode:
                self.is_drawing = True
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                self.stroke_points = [(x, y)]
                logging.info("[info] Started drawing stroke")
                return 0
            else:
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        elif msg == WM_MOUSEMOVE:
            if self.is_draw_mode and self.is_drawing:
                x = win32api.LOWORD(lparam)
                y = win32api.HIWORD(lparam)
                last_point = self.stroke_points[-1]
                self.stroke_points.append((x, y))
                logging.debug(f"[debug] Drawing line at {last_point} to {(x, y)} with color {self.draw_color_id}")
                self._draw_line(last_point, (x, y), self.draw_color)
                self._invalidate()
                return 0
            else:
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        elif msg == WM_RBUTTONUP:
            if self.is_draw_mode and self.is_drawing:
                self.is_drawing = False
                self.strokes.append((self.draw_color_id, list(self.stroke_points)))
                self.stroke_points.clear()
                logging.info("[info] Ended drawing stroke")
                return 0
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
        if hotkey_id in HOTKEY_IDS:
            mod, vk = HOTKEY_IDS[hotkey_id]
            color_num = vk - ord('0')
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

            # Show window now that we're drawing
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.UpdateWindow(self.hwnd)

            self._update_layered_window()

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

        # Hide window now that we're done drawing
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        self._update_layered_window()
        logging.info("[info] Alt released, exit draw mode")

    def _clear_bitmap(self):
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        # Fill with black = transparent because alpha channel is zero in DIB section
        brush = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        rect = (0, 0, screen_w, screen_h)
        win32gui.FillRect(self.memdc, rect, brush)

    def _draw_line(self, pt1, pt2, color):
        # GDI pens do not handle alpha, so lines will be fully opaque, which is fine for visibility.
        # We must convert RGB to BGR for GDI:
        r = color & 0xFF
        g = (color >> 8) & 0xFF
        b = (color >> 16) & 0xFF
        pen_color = win32api.RGB(b, g, r)

        pen = win32gui.CreatePen(win32con.PS_SOLID, 4, pen_color)
        old_pen = win32gui.SelectObject(self.memdc, pen)
        win32gui.MoveToEx(self.memdc, pt1[0], pt1[1])
        win32gui.LineTo(self.memdc, pt2[0], pt2[1])
        win32gui.SelectObject(self.memdc, old_pen)
        win32gui.DeleteObject(pen)

        self._update_layered_window()

    def _invalidate(self):
        win32gui.InvalidateRect(self.hwnd, None, True)

    def _on_paint(self):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        if not hdc:
            return
        # No need to BitBlt because UpdateLayeredWindow handles painting
        user32.EndPaint(self.hwnd, ctypes.byref(ps))

    def run(self):
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
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)
        logging.info("[info] Cleanup done")


if __name
