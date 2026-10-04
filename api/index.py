"""Vercel entrypoint: the StressLess FastAPI app, served under /api (see vercel.json)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from stressless.server.app import app  # noqa: E402

__all__ = ["app"]
