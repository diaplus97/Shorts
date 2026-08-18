#!/usr/bin/env python3
"""Standalone entry point: `python scripts/doctor.py`."""

from __future__ import annotations

import sys

from shorts_factory.scripts_doctor import run_doctor

if __name__ == "__main__":
    sys.exit(0 if run_doctor() else 1)
