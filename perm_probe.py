"""Probe & trigger every permission macOS needs for the demo pipeline.

Each step may show a system prompt — the user should click Allow for all.
Runs each probe with a timeout so a pending prompt never hangs the script.
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
TEMP = os.path.join(BASE, "temp")


def run(cmd, timeout=15):
    try:
        subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        return True
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print("  error:", e)
        return False


results = []

# 1. Screen recording (screencapture) — full-screen capture proves it.
ok = run(["screencapture", "-x", os.path.join(TEMP, "perm_probe.png")])
print(f"[1/3] Screen recording (screencapture): {'OK' if ok is True else 'pending/waiting prompt or failed'}")
results.append(ok)

# 2. Accessibility / control (pyautogui CGEvent) — move mouse safely to corner.
try:
    import pyautogui
    pyautogui.moveTo(5, 5, duration=0.2)
    ok = True
except Exception as e:
    ok = False
    print("  pyautogui error:", e)
print(f"[2/3] Accessibility / mouse control (pyautogui): {'OK' if ok else 'denied — add in System Settings > Privacy & Security > Accessibility'}")
results.append(ok)

# 3. Automation (AppleScript control of Telegram + WPS).
for app in ["Telegram", "wpsoffice"]:
    ok = run(["osascript", "-e", f'tell application "{app}" to activate'])
    print(f"[3/3] Automation control of {app}: {'OK' if ok is True else 'pending/waiting prompt or failed'}")
    results.append(ok)
    time.sleep(1)

print("---")
print("PROBE DONE. If any prompt appeared, click Allow/OK, then re-run to confirm.")
