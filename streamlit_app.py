"""Streamlit Community Cloud entry point for the shared persistent AeroTurn rehearsal."""
import os
import runpy
import sys
from pathlib import Path

os.environ["AEROTURN_COMMUNITY_CLOUD"] = "1"
os.environ.setdefault("AEROTURN_API","https://aeroturn-occ-rehearsal.vercel.app")
frontend = Path(__file__).resolve().parent / "frontend"
sys.path.insert(0, str(frontend))
runpy.run_path(str(frontend / "app.py"),run_name="__main__")
