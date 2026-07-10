import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        if k and v and k not in os.environ:
            os.environ[k.strip()] = v.strip().strip("'\"")

os.environ["MICUGPT2_NO_PROXY"] = "1"

from micugpt2_images_api import create_variation

r = create_variation(
    str(ROOT / "output" / "synthesized_20260529_100419.png"),
    str(ROOT / "output" / "synthesized_2048x512.png"),
    size="2048x512",
)
print(f"Result: {r}")
