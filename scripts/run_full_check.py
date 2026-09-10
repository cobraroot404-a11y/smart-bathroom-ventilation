#!/usr/bin/env python3
"""Runs every feasible automated check in this repository and prints a
pass/fail summary - this is the "single command" referenced throughout
docs/testing.md. Exits non-zero if any step fails or errors.

Steps:
  1. Firmware native unit tests (firmware/test/test_controller) - via
     `pio test -e native` if PlatformIO/a C++ toolchain is available,
     otherwise via a `gcc` Docker container (same sources/flags/Unity
     version - see docs/testing.md "Toolchain note").
  2. Automation service unit tests (pytest).
  3. Simulator unit tests (pytest).
  4. Scripted end-to-end demonstration (requires Docker).
  5. Energy-efficiency comparison report.

Usage: python scripts/run_full_check.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: List[str], cwd: Path = None) -> int:
    print(f"$ {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return result.returncode


def step_firmware_native_tests() -> Tuple[bool, str]:
    firmware_dir = REPO_ROOT / "firmware"
    if have("pio") or have("platformio"):
        exe = "pio" if have("pio") else "platformio"
        rc = run([exe, "test", "-e", "native"], cwd=firmware_dir)
        return rc == 0, "pio test -e native"

    if not have("docker"):
        return False, "SKIPPED - neither PlatformIO nor Docker is available"

    print("PlatformIO not found on PATH; building via a gcc Docker "
          "container instead (same sources/flags/Unity version - see "
          "docs/testing.md).")
    with tempfile.TemporaryDirectory() as _:
        script = (
            "set -e; cd /tmp; "
            "git clone --depth 1 --branch v2.6.0 "
            "https://github.com/ThrowTheSwitch/Unity.git unity >/dev/null 2>&1; "
            "g++ -std=gnu++17 -Wall -Wextra -DUNIT_TEST -I/work/include "
            "-I/tmp/unity/src -c /tmp/unity/src/unity.c -o /tmp/unity.o; "
            "g++ -std=gnu++17 -Wall -Wextra -DUNIT_TEST -I/work/include "
            "-c /work/src/controller.cpp -o /tmp/controller.o; "
            "g++ -std=gnu++17 -Wall -Wextra -DUNIT_TEST -I/work/include "
            "-I/tmp/unity/src -c /work/test/test_controller/test_main.cpp "
            "-o /tmp/test_main.o; "
            "g++ /tmp/unity.o /tmp/controller.o /tmp/test_main.o -o /tmp/test_controller; "
            "/tmp/test_controller"
        )
        rc = run([
            "docker", "run", "--rm",
            "-v", f"{firmware_dir}:/work",
            "-w", "/work",
            "gcc:13", "bash", "-c", script,
        ])
        return rc == 0, "Dockerized gcc build + Unity run"


def step_pytest(package_dir: Path) -> Tuple[bool, str]:
    rc = run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=package_dir)
    return rc == 0, "pytest tests/"


def step_e2e_demo() -> Tuple[bool, str]:
    if not have("docker"):
        return False, "SKIPPED - Docker is not available"
    rc = run([sys.executable, "simulator/simulator/run_e2e_demo.py"], cwd=REPO_ROOT)
    return rc == 0, "run_e2e_demo.py"


def step_energy_report() -> Tuple[bool, str]:
    rc = run([sys.executable, "energy/energy_report.py"], cwd=REPO_ROOT)
    return rc == 0, "energy_report.py"


def main() -> int:
    steps: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
        ("Firmware native unit tests", step_firmware_native_tests),
        ("Automation service unit tests", lambda: step_pytest(REPO_ROOT / "automation")),
        ("Simulator unit tests", lambda: step_pytest(REPO_ROOT / "simulator")),
        ("End-to-end simulated demonstration", step_e2e_demo),
        ("Energy-efficiency report", step_energy_report),
    ]

    results = []
    for name, fn in steps:
        print(f"\n{'=' * 78}\n{name}\n{'=' * 78}")
        try:
            ok, detail = fn()
        except Exception as e:  # pragma: no cover - defensive
            ok, detail = False, f"raised {type(e).__name__}: {e}"
        results.append((name, ok, detail))

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    all_ok = True
    for name, ok, detail in results:
        status = "PASS" if ok else ("SKIP" if "SKIPPED" in detail else "FAIL")
        if status == "FAIL":
            all_ok = False
        print(f"  [{status:4}] {name:<38} ({detail})")

    if not all_ok:
        print("\nOne or more checks failed. Do not publish until all feasible "
              "checks pass - see docs/testing.md.")
        return 1

    print("\nAll feasible automated checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
