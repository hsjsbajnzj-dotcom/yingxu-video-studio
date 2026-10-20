"""Portable, local-only configuration. Importing this module creates no files."""
import json
import os
import shutil
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.environ.get('YINGXU_CONFIG', PACKAGE.parent / 'config.local.json')).resolve()
BASE = CONFIG_FILE.parent


def load_config(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError('配置文件无法读取，请检查JSON格式') from exc
    if not isinstance(value, dict):
        raise ValueError('配置顶层必须是JSON对象')
    for key in ['paths', 'tools', 'engines', 'features']:
        if key in value and not isinstance(value[key], dict):
            raise ValueError('配置区块必须是对象：' + key)
    return value


SETTINGS = load_config(CONFIG_FILE)


def resolve(value, base=BASE):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('配置路径不能为空')
    path = Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else Path(base) / path).resolve()


STATE = resolve(os.environ.get('YINGXU_DATA_DIR', SETTINGS.get('paths', {}).get('state', 'runtime')))


def path(name, default):
    return resolve(SETTINGS.get('paths', {}).get(name, str(default)))


H3 = path('h3_root', STATE / 'h3')
MODELS = path('models', H3 / 'models')
INPUT = path('input', H3 / 'input')
MEDIA = {name: path(name + '_output', STATE / 'outputs' / name) for name in ['h3', 'wangp', 'assets']}
LOGS = STATE / 'logs'


def executable(name, default=None):
    value = SETTINGS.get('tools', {}).get(name) or default or name
    if not isinstance(value, str):
        raise ValueError('工具路径必须是字符串：' + name)
    if '/' in value or '\\' in value:
        return str(resolve(value))
    return shutil.which(value) or value


FFMPEG = executable('ffmpeg')
FFPROBE = executable('ffprobe')


def feature(name):
    value = SETTINGS.get('features', {}).get(name, False)
    if not isinstance(value, bool):
        raise ValueError('可选功能开关必须是true或false：' + name)
    return value


def engines():
    result = {}
    for key, kind, port in [('comfy_stable','comfy',8188), ('comfy_latest','comfy',8189),
                            ('wangp_stable','wangp',7866), ('wangp_latest','wangp',7867)]:
        raw = SETTINGS.get('engines', {}).get(key, {})
        if not isinstance(raw, dict):
            raise ValueError('引擎配置必须是对象：' + key)
        configured = bool(raw.get('root'))
        root = resolve(raw['root']) if configured else STATE / 'unconfigured' / key
        chosen_port = raw.get('port', port)
        if isinstance(chosen_port,bool) or not isinstance(chosen_port,int) or not 1 <= chosen_port <= 65535:
            raise ValueError('引擎端口应为1–65535整数')
        result[key] = dict(id=key, name=('ComfyUI / H3' if kind=='comfy' else 'WanGP') + (' 主入口' if key.endswith('stable') else ' 试验入口'),
                           version=raw.get('version','用户自行安装'), kind=kind, port=chosen_port,
                           configured=configured, root=str(root),
                           python=str(resolve(raw['python'])) if raw.get('python') else '',
                           base_directory=str(resolve(raw['base_directory'])) if raw.get('base_directory') else str(root),
                           note='未配置；可先使用界面与项目管理' if not configured else '外部独立引擎，能力及效果需本机验收')
    active=[e['port'] for e in result.values() if e['configured']]
    if len(set(active)) != len(active):
        raise ValueError('引擎端口不能重复')
    return result


def comfy_url():
    return 'http://127.0.0.1:' + str(engines()['comfy_stable']['port'])
