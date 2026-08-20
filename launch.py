#!/usr/bin/env python3
"""
launch.py — Single-command entrypoint for Agnostic AI Harness.
Inspects harness health, validates sync, and launches the web dashboard.
"""

import os
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print("==================================================")
    print("           AGNOSTIC AI AGENT HARNESS             ")
    print("==================================================")
    print(f"Root: {ROOT_DIR}\n")

    # 0. First-Run Default Harness Onboarding Check
    print("[0/4] Checking default harness installation & skill consolidation...")
    subprocess.run(["node", "engine/setup/first-run.cjs"], cwd=ROOT_DIR)

    # 1. Run Parity Check
    print("\n[1/4] Checking harness parity across 18 clients...")
    subprocess.run(["node", "engine/sync/sync.cjs", "--check"], cwd=ROOT_DIR)

    # 2. Check DashClaw Governed Autonomy Integration
    print("\n[2/4] Inspecting DashClaw integration & self-configuration...")
    subprocess.run(["node", "engine/hooks/dashclaw-setup.cjs"], cwd=ROOT_DIR)

    # 3. Run Self-Tests (advisory — a failing self-check must not block the dashboard)
    print("\n[3/4] Running engine test suite...")
    test_run = subprocess.run(["node", "engine/tests/run-all.cjs"], cwd=ROOT_DIR)
    if test_run.returncode != 0:
        print(
            "\n[WARNING] Engine self-test suite failed. Review errors above; launching dashboard anyway."
        )

    # 4. Launch Dashboard
    print("\n[4/4] Launching Agnostic AI Universal Command Center...")
    server_process = subprocess.Popen(
        ["node", "tools/dashboard/dashboard.cjs", "--open"], cwd=ROOT_DIR
    )

    print("\nCommand Center running on http://127.0.0.1:7842")
    print("Press Ctrl+C to stop.")

    try:
        server_process.wait()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server_process.terminate()


if __name__ == "__main__":
    main()
