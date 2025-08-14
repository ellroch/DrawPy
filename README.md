# DrawPy

# tray_draw_overlay

A headless, GPU-accelerated, system-tray–driven Python overlay for on-screen drawing. Listens for **Ctrl+Alt+<number> + Right-Click**, draws while **Ctrl+Alt** are held, and clears when released.

---

## 📦 Installation

1. Ensure **Python 3.8+** is installed.
2. Install dependencies:

   ```bash
   pip install pyqt5 pynput pystray pillow PyOpenGL
   ```

3. Place `launcher.py` (or a `.pyw` wrapper) alongside the `tray_draw_overlay` package.

---

## 🔧 Usage

- Run with:
  ```bat
  start "" pythonw path\to\tray_draw_overlay\launcher.pyw
  ```
- System tray icon appears. Use left- or right-click for context menu:
  - **Toggle Drawing** (enable/disable overlay)
  - **Exit**

---

## 🗂️ Package Structure

```
tray_draw_overlay/
├── __init__.py
├── listener.py      # Keyboard & mouse listener with enable/disable
├── overlay.py       # Transparent, full-screen GPU-backed drawing canvas
└── tray.py          # System tray icon & context menu with left/right click

launcher.py          # External .pyw launcher script
``` 

---

## ⚙️ GPU-Accelerated Overlay

- Uses `QOpenGLWidget` to offload stroke rendering to the GPU.  
- Maintains a persistent, borderless, transparent window (hidden/shown on trigger) to avoid OS window overhead.  
- Throttles repaints at 60 FPS using a `QTimer`.

---