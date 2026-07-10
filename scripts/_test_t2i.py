import sys, os
os.environ["HTTPS_PROXY"] = ""
os.environ["https_proxy"] = ""
os.environ["HTTP_PROXY"] = ""
os.environ["http_proxy"] = ""

from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        if k and v and k not in os.environ:
            os.environ[k.strip()] = v.strip().strip("'\"")

_gen_scripts = ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts"
sys.path.insert(0, str(_gen_scripts))
from generate_from_description import _generate_image_micugpt2

prompt = (
    "A stunning ultra-wide game banner composition. "
    "Three game characters standing heroically in the center third of the frame. "
    "Immersive cinematic background. High quality CG illustration. "
    "Dramatic lighting, vibrant colors. No text."
)

result = _generate_image_micugpt2(
    prompt,
    str(ROOT / "output" / "test_t2i_2048x512.png"),
    size="2048x512",
)
print(f"Result: {result}")

if result and result.is_file():
    from PIL import Image
    im = Image.open(str(result))
    print(f"Size: {im.size[0]}x{im.size[1]}")
