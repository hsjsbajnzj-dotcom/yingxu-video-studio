"""Portable launcher: use the already installed local web venv."""
import subprocess
import sys
from pathlib import Path

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    python=root/'.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if not python.is_file():raise SystemExit('请先运行 python install_web.py --media 安装网页环境')
    raise SystemExit(subprocess.call([str(python),str(root/'simple_video_studio/studio.py'),*sys.argv[1:]],cwd=root))
