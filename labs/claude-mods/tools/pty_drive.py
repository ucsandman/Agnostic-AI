"""Drive an interactive `claude` session through a Windows pseudo-terminal and render its screen with pyte.

Usage:
  python tools/pty_drive.py <outfile> <startup-wait-s> "<plugin-dir>[,<plugin-dir>...]" "<prompt>|||<prompt>..." <turn-wait-s> "<keys>|||<keys>..." [extra claude args...]

- Each prompt is typed, Enter pressed, then the driver waits <turn-wait-s> (snapshotting every 5 s).
- Each keys segment is sent raw after all prompts (escape sequences allowed: \\r Enter, \\x1b Esc, \\t Tab), 3 s apart.
- Snapshots go to <outfile>; the final screen is printed. Terminal is 150x45 so panes can dock (>=144 cols).
"""

import sys
import time
import threading
import winpty
import pyte

out_path, wait, plugin_dirs = sys.argv[1], float(sys.argv[2]), sys.argv[3]
prompts = [
    p
    for p in (sys.argv[4].split("|||") if len(sys.argv) > 4 and sys.argv[4] else [])
    if p
]
turn_wait = float(sys.argv[5]) if len(sys.argv) > 5 else 45.0
keys = [
    k.encode().decode("unicode_escape")
    for k in (sys.argv[6].split("|||") if len(sys.argv) > 6 and sys.argv[6] else [])
    if k
]
extra = " ".join(sys.argv[7:])
COLS, ROWS = 150, 45
pd = " ".join(f"--plugin-dir {d}" for d in plugin_dirs.split(",") if d)
cmd = f"claude {pd} --model haiku {extra}".strip()
p = winpty.PtyProcess.spawn(
    cmd, dimensions=(ROWS, COLS), cwd="C:/Projects/claude-mods-rnd"
)
screen = pyte.Screen(COLS, ROWS)
stream = pyte.ByteStream(screen)
lock = threading.Lock()
stop = False
snaps = []


def reader():
    while not stop:
        try:
            chunk = p.read(4096)
            if chunk:
                with lock:
                    stream.feed(chunk.encode("utf-8", "replace"))
        except Exception:
            if not p.isalive():
                break
            time.sleep(0.05)


def snap(label):
    with lock:
        text = "\n".join(line.rstrip() for line in screen.display)
    snaps.append(f"===== {label} @ {time.strftime('%H:%M:%S')} =====\n{text}\n")


threading.Thread(target=reader, daemon=True).start()
time.sleep(wait)
snap("after startup")
for i, prompt in enumerate(prompts):
    if prompt.startswith(
        "KEYS:"
    ):  # raw keystrokes mid-sequence (answer a dialog, run a slash command)
        p.write(prompt[5:].encode().decode("unicode_escape"))
        time.sleep(4)
        snap(f"step {i + 1} keys sent")
        continue
    if prompt.startswith("WAIT:"):
        time.sleep(float(prompt[5:]))
        snap(f"step {i + 1} waited")
        continue
    p.write(prompt)
    time.sleep(1.0)
    p.write("\r")
    t_end = time.time() + turn_wait
    while time.time() < t_end:
        time.sleep(5)
        snap(f"prompt {i + 1} in progress")
    snap(f"prompt {i + 1} done")
for i, k in enumerate(keys):
    p.write(k)
    time.sleep(3)
    snap(f"after keys {i + 1}")
p.write("/exit")
time.sleep(0.8)
p.write("\r")
time.sleep(3)
snap("after /exit")
stop = True
try:
    p.terminate(force=True)
except Exception:
    pass
open(out_path, "w", encoding="utf-8").write("\n".join(snaps))
print(snaps[-2] if len(snaps) > 1 else snaps[-1])
