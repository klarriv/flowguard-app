"""Put app/ on sys.path, as `streamlit run app/app.py` does, so `components` imports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
