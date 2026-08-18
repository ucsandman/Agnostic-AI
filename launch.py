#!/usr/bin/env python3
"""
launch.py — Single-command entrypoint for Agnostic AI Harness.
Inspects harness health, validates sync, and launches the web dashboard.
"""

import os
import sys
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print("==================================================")
    print("           AGNOSTIC AI AGENT HARNESS             ")
    print("==================================================")
    print(f"Root: {ROOT_DIR}\n")

    # 1. Run Parity Check
    print("[1/3] Checking harness parity across clients...")
    subprocess.run(["node", "engine/sync/sync.cjs", "--check"], cwd=ROOT_DIR)

    # 2. Run Self-Tests
    print("\n[2/3] Running engine test suite...")
    test_run = subprocess.run(["node", "engine/tests/run-all.cjs"], cwd=ROOT_DIR)
    if test_run.returncode != 0:
        print("\n[ERROR] Test suite failed. Please review errors above.")
        sys.exit(1)

    # 3. Launch Dashboard
    print("\n[3/3] Launching Agnostic Error & Parity Dashboard...")
    server_process = subprocess.Popen(
        ["node", "tools/errorlog/errorlog.cjs", "--open"], cwd=ROOT_DIR
    )

    print("\nServer running on http://127.0.0.1:7842")
    print("Press Ctrl+C to stop.")

    try:
        server_process.wait()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server_process.terminate()


if __name__ == "__main__":
    main()
