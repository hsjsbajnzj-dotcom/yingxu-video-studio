"""Create a web-only venv. Never installs engines, CUDA, weights or node packs."""
import argparse
import json
import subprocess
import sys
import venv
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='安装映序网页环境，不安装视频模型')
    parser.add_argument('--media',action='store_true',help='同时安装CPU拆镜组件；FFmpeg仍需单独准备')
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,12):raise SystemExit('当前安装器只验收Python3.12，请先安装该版本；不会替换系统Python')
    root=Path(__file__).resolve().parent
    target=(root/'.venv').resolve()
    if not target.is_relative_to(root):raise SystemExit('拒绝使用候选目录外的环境路径')
    python=target/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if target.exists() and not python.is_file():raise SystemExit('已有.venv但缺少Python，请人工检查；不会删除它')
    if not python.is_file():venv.EnvBuilder(with_pip=True).create(target)
    requirement=root/('requirements-media.txt' if args.media else 'requirements.txt')
    command=[str(python),'-m','pip','--isolated','install','--index-url','https://pypi.org/simple',
             '--only-binary=:all:','-r',str(requirement)]
    if sys.platform=='win32':command+=['-c',str(root/'constraints-win-py312.txt')]
    subprocess.run(command,check=True)
    config=root/'config.local.json'
    if not config.exists():
        sample=json.loads((root/'config.example.json').read_text(encoding='utf-8'))
        with config.open('x',encoding='utf-8') as f:json.dump(sample,f,ensure_ascii=False,indent=2)
    print('网页环境已准备。请运行.venv中的Python执行 simple_video_studio/studio.py --doctor 检查配置。')
    print('已有配置未覆盖。没有安装模型或启动任何引擎。')


if __name__=='__main__':main()
