"""Read-only first-run checks; no model loading, downloads or engine startup."""
import importlib.util
import subprocess
import sys
from pathlib import Path
import studio_config as config


def installed(name):
    try:return importlib.util.find_spec(name) is not None
    except (ImportError,ValueError):return False


def tool(name):
    command=config.executable(name)
    try:
        result=subprocess.run([command,'-version'],capture_output=True,timeout=8,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        ok=result.returncode==0
    except (OSError,subprocess.TimeoutExpired):ok=False
    return {'ready':ok,'hint':'已找到' if ok else f'请自行安装{name}并加入PATH，或在tools.{name}填写路径；工作室不会自动下载'}


def diagnose():
    engines=[]
    for key,engine in config.engines().items():
        root=Path(engine['root'])
        entry=root/('main.py' if engine['kind']=='comfy' else 'app/wgp.py')
        ready=engine['configured'] and entry.is_file() and bool(engine['python']) and Path(engine['python']).is_file()
        engines.append({'id':key,'configured':engine['configured'],'launch_files_ready':bool(ready),
                        'hint':'仅启动文件检查通过，模型/接口/出片仍需验收' if ready else '请在配置文件中填写引擎根目录和其独立Python路径'})
    tools={key:tool(key) for key in ['ffmpeg','ffprobe']}
    return {'python':sys.version.split()[0], 'basic_ready':sys.version_info>=(3,10) and installed('psutil'),
            'media_ready':all(t['ready'] for t in tools.values()) and installed('scenedetect'),
            'tools':tools,'scenedetect':installed('scenedetect'),'engines':engines,
            'optional_features':{key:config.feature(key) for key in ['mmaudio','realesrgan','seedvr2','flashvsr']},
            'scope':'仅本地配置与依赖检查，不代表视频模型已装好或画质验收通过',
            'next_step':'未配置引擎也可先使用网页和分镜管理；生成前另行安装并配置支持的引擎与模型'}
