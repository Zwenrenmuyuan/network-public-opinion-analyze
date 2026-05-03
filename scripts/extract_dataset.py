"""解压 SMP2020-EWECT 评测数据集 zip 到 data/raw/。

zip 包内的文件名是 UTF-8 编码但没设置 ZIP_FILENAME_FLAG_UTF8 标志位，
Python 的 zipfile 默认会按 cp437 解码出乱码，所以这里手动 cp437 → utf-8 还原。

zip 密码默认是 SMP2020 官方公开的 'smp2020ewect'，可用 --password 覆盖。

用法：
    uv run python scripts/extract_dataset.py
    uv run python scripts/extract_dataset.py --zip path/to/x.zip --dest path/to/out
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP = ROOT / 'data' / '评测数据集加密.zip'
DEFAULT_DEST = ROOT / 'data' / 'raw'
DEFAULT_PASSWORD = 'smp2020ewect'


def _decode_name(raw: str) -> str:
    """zipfile 把 UTF-8 字节按 cp437 解了码，这里反向还原。"""
    try:
        return raw.encode('cp437').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def extract(zip_path: Path, dest: Path, password: str) -> tuple[int, int]:
    """解压到 dest，已存在的文件跳过。返回 (写入数, 跳过数)。"""
    written = skipped = 0
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    with zipfile.ZipFile(zip_path) as zf:
        zf.setpassword(password.encode())
        for info in zf.infolist():
            name = _decode_name(info.filename)
            if name.endswith('/.DS_Store') or name == '.DS_Store':
                continue

            target = dest / name
            # zip slip 防护：解析后路径必须仍在 dest 下
            if not target.resolve().is_relative_to(dest_resolved):
                raise RuntimeError(f'zip slip 检测到逃逸路径: {name!r}')

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                skipped += 1
                continue

            with zf.open(info) as src, open(target, 'wb') as out:
                out.write(src.read())
            written += 1

    return written, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--zip', type=Path, default=DEFAULT_ZIP, help=f'默认 {DEFAULT_ZIP}')
    parser.add_argument('--dest', type=Path, default=DEFAULT_DEST, help=f'默认 {DEFAULT_DEST}')
    parser.add_argument('--password', default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    if not args.zip.exists():
        raise SystemExit(f'zip 不存在: {args.zip}')

    written, skipped = extract(args.zip, args.dest, args.password)
    print(f'写入 {written} 个文件，跳过 {skipped} 个已存在文件，输出目录: {args.dest}')


if __name__ == '__main__':
    main()
