import subprocess, sys, os
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
r = subprocess.run(
    [sys.executable, os.path.join(_base, "scripts", "run_all_presets.py"), "@",
     "-m", "无纸化进阶神器",
     "-s", "打造你的数字知识库",
     "-g", "商店移动端日常",
     "--packy3s"],
    capture_output=False, text=True, encoding="utf-8",
)
sys.exit(r.returncode)
