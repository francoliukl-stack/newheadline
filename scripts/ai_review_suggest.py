from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ai_review_job import run  # noqa: E402

raise SystemExit(run("suggest"))
