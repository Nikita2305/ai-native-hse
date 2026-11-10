#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ai_native_hse.common import entry
from ai_native_hse.roots import main

entry(main)
