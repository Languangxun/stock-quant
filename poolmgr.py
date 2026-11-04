#!/usr/bin/env python3
"""股票池维护工具：向指定文件（默认 input/pool.txt）添加、删除或列出股票。"""

import concurrent.futures
import os
import re
import sys
import urllib.request

import click

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    _cwd_pool = os.path.join(os.getcwd(), 'input', 'pool.txt')
    DEFAULT_POOL_PATH = (_cwd_pool if os.path.exists(_cwd_pool)
                         else os.path.join(BASE_DIR, 'input', 'pool.txt'))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DEFAULT_POOL_PATH = os.path.join(BASE_DIR, 'input', 'pool.txt')

_CODE_RE = re.compile(r'(?i)^(?:sh|sz|bj)?(\d{6})$')


def _normalize_code(token):
    m = _CODE_RE.fullmatch(token)
    return m.group(1) if m else token


def _parse_codes(text):
    codes = [_normalize_code(x) for x in re.split(r'[,\s]+', text or '') if x]
    return list(dict.fromkeys(codes))


def _parse_entries(text):
    entries = {}
    current = None
    for token in re.split(r'[,\s]+', text or ''):
        token = token.strip()
        if not token:
            continue
        m = _CODE_RE.fullmatch(token)
        if m:
            current = m.group(1)
            entries.setdefault(current, '')
        elif current:
            entries[current] = f'{entries[current]} {token}'.strip()
    return entries


def _resolve_pool_path(file_path):
    if not file_path:
        return DEFAULT_POOL_PATH
    return os.path.abspath(os.path.expanduser(file_path))


def _resolve_input_path(file_path):
    path = os.path.abspath(os.path.expanduser(file_path))
    if os.path.isfile(path):
        return path
    if not os.path.isabs(file_path):
        for candidate in (os.path.join('input', file_path),
                          os.path.join('input', os.path.basename(file_path)),
                          os.path.join(BASE_DIR, 'input', file_path),
                          os.path.join(BASE_DIR, 'input', os.path.basename(file_path))):
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
    return None


def _read_file_entries(path):
    with open(path, 'r', encoding='utf-8') as f:
        return _parse_entries(f.read())


def _sina_symbol(code):
    if code.startswith(('6', '9')):
        return f'sh{code}'
    if code.startswith(('0', '3', '2', '15')):
        return f'sz{code}'
    if code.startswith(('4', '8')):
        return f'bj{code}'
    return f'sh{code}'


def _fetch_name(code):
    if not re.fullmatch(r'\d{6}', code):
        return ''
    url = f'https://hq.sinajs.cn/list={_sina_symbol(code)}'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://finance.sina.com.cn/',
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode('gbk', errors='ignore')
    except Exception:
        return ''
    match = re.search(r'"([^"]*)"', text)
    if not match:
        return ''
    return match.group(1).split(',', 1)[0].strip()


def _fetch_names(codes):
    if not codes:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(codes))) as ex:
        return dict(zip(codes, ex.map(_fetch_name, codes)))


def _format_entries(entries):
    return ', '.join(f'{code} {name}' if name else code for code, name in entries)


@click.command(no_args_is_help=True)
@click.option('--add', '-add', default=None,
              help='要添加的股票代码，多个以空格/逗号分隔（自动查询名称，写入格式：代码 名称）')
@click.option('--addf', '-addf', 'add_file', default=None,
              help='从文件读取股票代码并加入股票池')
@click.option('--rm', '-rm', 'remove', default=None,
              help='要删除的股票代码，多个以空格/逗号分隔（如 "600036 000001"）')
@click.option('--rmf', '-rmf', 'rm_file', default=None,
              help='从文件读取股票代码并从股票池删除')
@click.option('--file', '-f', 'file_path', default=None,
              help='股票池文件路径（默认 input/pool.txt）')
@click.option('--list', '-l', 'list_codes', is_flag=True, default=False,
              help='打印股票列表（代码 名称）')
def poolmgr(add, add_file, remove, rm_file, file_path, list_codes):
    """维护股票池：添加、删除或列出股票

    添加时会自动查询股票名称，按“代码 名称”格式写入：
        python3 poolmgr.py -add "600036 000001"
        python3 poolmgr.py -addf input/favs.txt
        python3 poolmgr.py -rm "000001"
        python3 poolmgr.py -rmf input/old_pool.txt
        python3 poolmgr.py -f input/my_pool.txt -l
    """
    pool_path = _resolve_pool_path(file_path)

    add_specs = {c: '' for c in _parse_codes(add)}
    if add_file:
        src_path = _resolve_input_path(add_file)
        if src_path is None:
            click.echo(click.style(f'  错误: 文件不存在: {add_file}', fg='red'))
            return
        src_entries = _read_file_entries(src_path)
        if not src_entries:
            click.echo(click.style(f'  提示: 文件内未找到股票代码: {src_path}', fg='yellow'))
        for code, name in src_entries.items():
            if not add_specs.get(code):
                add_specs[code] = name

    rm_codes = _parse_codes(remove)
    if rm_file:
        src_path = _resolve_input_path(rm_file)
        if src_path is None:
            click.echo(click.style(f'  错误: 文件不存在: {rm_file}', fg='red'))
            return
        src_entries = _read_file_entries(src_path)
        if not src_entries:
            click.echo(click.style(f'  提示: 文件内未找到股票代码: {src_path}', fg='yellow'))
        rm_codes.extend(src_entries.keys())
    rm_codes = list(dict.fromkeys(rm_codes))

    has_modify = bool(add_specs or rm_codes)

    if not has_modify and not list_codes:
        click.echo(click.style('  错误: 请使用 -add、-addf、-rm、-rmf 或 -l 指定操作', fg='red'))
        return

    entries = {}
    if os.path.exists(pool_path):
        with open(pool_path, 'r', encoding='utf-8') as f:
            entries = _parse_entries(f.read())
    before_count = len(entries)

    if has_modify:
        need_name = [c for c, name in add_specs.items()
                     if (c not in entries or not entries[c]) and not name]
        names = _fetch_names(need_name)
        added = []
        filled = []
        failed = []

        for code, hint in add_specs.items():
            if code not in entries:
                name = hint or names.get(code, '')
                entries[code] = name
                added.append((code, name))
                if not name:
                    failed.append(code)
            elif not entries[code]:
                name = hint or names.get(code, '')
                if name:
                    entries[code] = name
                    filled.append((code, name))
                else:
                    failed.append(code)

        rm_set = set(rm_codes)
        removed = [c for c in entries if c in rm_set]
        for code in rm_codes:
            entries.pop(code, None)
        missing = [c for c in rm_codes if c not in removed]

        os.makedirs(os.path.dirname(pool_path), exist_ok=True)
        with open(pool_path, 'w', encoding='utf-8') as f:
            for code, name in entries.items():
                f.write(f'{code} {name}\n' if name else f'{code}\n')

        if added:
            click.echo(click.style(f'  已添加: {_format_entries(added)}', fg='green'))
        if filled:
            click.echo(click.style(f'  已补充名称: {_format_entries(filled)}', fg='green'))
        if failed:
            click.echo(click.style(f'  未获取到名称: {" ".join(failed)}', fg='yellow'))
        if removed:
            click.echo(click.style(f'  已删除: {" ".join(removed)}', fg='yellow'))
        if missing:
            click.echo(click.style(f'  未找到: {" ".join(missing)}', fg='red'))
        if not added and not filled and not failed and add_specs:
            click.echo(click.style('  添加的代码均已存在', fg='cyan'))
        click.echo(click.style(
            f'  股票池: {before_count} 只 -> {len(entries)} 只 ({pool_path})', fg='cyan'))

    if list_codes:
        if entries:
            click.echo('\n'.join(f'{code} {name}' if name else code
                                 for code, name in entries.items()))
        else:
            click.echo(click.style('  股票池为空', fg='cyan'))


if __name__ == '__main__':
    poolmgr()
