"""Explicit image roles shared by preflight and H3 graph export."""
from pathlib import Path

MAX_REFERENCES = 6  # Conservative studio limit, not the model's theoretical maximum.
TAKES = {'full', 'person', 'scene', 'object', 'style'}


def image_assets(data, input_root=None):
    first = str(data.get('input_asset') or '').strip()
    last = str(data.get('end_asset') or '').strip()
    refs = data.get('reference_assets') or []
    if not isinstance(refs, list) or len(refs) > MAX_REFERENCES:
        raise ValueError('参考图片需要是列表，工作室目前最多添加6张参考图')
    if (last or refs) and data.get('provider', 'local_h3') != 'local_h3':
        raise ValueError('当前只有本地H3接通首尾帧和多图参考；请切换本地H3或移除附加图片')
    if data.get('mode', 'text') != 'image':
        if last or refs:
            raise ValueError('添加首尾帧或参考图后请选择图片＋文字模式')
        return []
    assets = []
    def add(filename, role, takes='full', kind='image'):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError('图片路径不能为空')
        filename = filename.strip()
        if kind not in {'image', 'video'} or (kind == 'video' and role != 'reference'):
            raise ValueError('视频只能用作运动参考')
        allowed_takes = TAKES if kind == 'image' else {'motion', 'camera', 'full'}
        if takes not in allowed_takes:
            raise ValueError('参考用途只能选择人物、场景、物品、风格或整体')
        if input_root is not None:
            root = Path(input_root).resolve()
            path = (root / filename).resolve()
            extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'} if kind == 'image' else {'.mp4', '.mov', '.webm', '.mkv'}
            if not path.is_relative_to(root) or path.suffix.lower() not in extensions:
                raise ValueError('图片路径不在工作室输入目录内或格式不支持')
            if not path.is_file():
                raise ValueError('图片不存在，请重新上传：' + Path(filename).name)
        assets.append({'handle': f'img-{len(assets)+1}', 'kind': kind, 'role': role,
                       'takes': takes, 'filename': filename})
        if kind == 'video':
            assets[-1]['track'] = 'picture'
    if first:
        add(first, 'first_frame')
    if last:
        add(last, 'last_frame')
    if sum(r.get('kind') == 'video' for r in refs if isinstance(r, dict)) > 1:
        raise ValueError('一次最多一条3D预演运动参考视频')
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError('参考图缺少路径和用途')
        add(ref.get('input_asset'), 'reference', ref.get('takes', 'full'), ref.get('kind', 'image'))
    if not assets:
        raise ValueError('请至少上传一张首帧、尾帧或参考图片')
    return assets
