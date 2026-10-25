"""Build the complete sibling 3DS bundle, including matching apps and source."""
import runpy
from pathlib import Path
if __name__ == "__main__":runpy.run_path(str(Path(__file__).resolve().parent.parent/"build_bundle.py"),run_name="__main__")
