import os

# The older suites test the simulated demo dataset; the app itself runs on real data (see server/session.py).
os.environ.setdefault("STRESSLESS_DATA", "demo")
