import sys
from pathlib import Path

# make `import sourcing` work from any folder (repo root = two levels up)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
