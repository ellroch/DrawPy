Got it — you want the **entire README in clean, copy-paste-ready Markdown** with no extra commentary.

Here’s the final version:

````markdown
# DrawPy

A lightweight, hotkey-driven drawing overlay for Windows. Draw directly over the entire virtual desktop (all monitors) without interrupting applications — useful for presentations, streaming, teaching, or quick annotations.

---

## Features

- **Hotkey-driven activation and color selection**
  - `Alt + Shift + 1..4` — enter draw mode and select a color
  - `Alt + 1..4` — switch color while in draw mode
- **Two stroke behaviors**
  - **Right-click + drag** → persistent strokes (remain until you exit draw mode)
  - **Left-click + drag** → temporary strokes (erased on mouse-up)
- **Click-through when inactive** — overlay does not block interaction with other apps when not in draw mode
- **Multi-monitor support** — covers the full virtual desktop
- **System tray icon** — quick access to exit the app
- **Simple, minimal dependencies**

**Default color mapping**
- `1` = Red  
- `2` = Green  
- `3` = Blue  
- `4` = Yellow

---

## Installation / Setup

### Requirements
- Windows 10 or later  
- Python 3.10 or newer

### Dependencies
Install required Python packages:
```bash
pip install pywin32 Pillow pystray
````

### Run

From the folder containing `drawpy.py`:

```bash
python drawpy.py
```

> If a hotkey fails to register, another program may already use that combination. Edit `HOTKEY_IDS` in the source to change the bindings before running.

---

## How to Use

1. **Start DrawPy**
   Run `python drawpy.py`. A pencil icon appears in the system tray. The overlay is hidden until activated.

2. **Enter draw mode (and pick a color)**
   Hold `Alt + Shift + <number>` to enter draw mode with the chosen color:

   * `Alt + Shift + 1` → Red
   * `Alt + Shift + 2` → Green
   * `Alt + Shift + 3` → Blue
   * `Alt + Shift + 4` → Yellow

3. **Draw**

   * **Right-click + drag**: create **persistent** strokes (they remain).
   * **Left-click + drag**: create **temporary** strokes (cleared on mouse release).

4. **Change color while drawing**
   While still in draw mode, press `Alt + 1..4` (no Shift) to change the active color.

5. **Exit draw mode**
   Release the `Alt` key — the overlay clears all strokes and returns to click-through mode.

6. **Quit DrawPy**
   Right-click the system tray icon and select **Exit DrawPy**.

```

Do you want me to also include a **hotkey reference table** in this Markdown so it’s more visual? That would make it easier for end users to scan.
```
