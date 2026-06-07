import sys
from pathlib import Path

# Make vendor/ importable (waveshare_epd lives there)
_vendor = Path(__file__).parent.parent.parent / "vendor"
if _vendor.exists() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))
