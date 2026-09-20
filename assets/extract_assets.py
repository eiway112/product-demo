#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从已交付的单文件演示件 HTML 反提图片与内联数据集，固化到持久目录。

为什么需要：中间产物放 %TEMP% 会被静默清零（实测）。反提出来的资产必须落项目目录/git 仓。

用法：
  python extract_assets.py --html <成品.html> --out-dir <资产目录>
                           [--images "logo.png:0,hero.png:1"]
                           [--data-name items.json]

行为（全部按结构识别，不依赖任何产品字段名）：
  1. 按出现顺序抽取 data:image 内联图 → PNG/JPEG 文件；
  2. 抽取 HTML 里所有 `var <名字> = <数组或对象字面量>;`，逐个转成 JSON 存进一个文件，
     键名就是变量名（例如契约里的 IX_ITEMS / IX_AXIS 会被原样提出来）；
  3. 回验：反提出来的每个数值都必须在 HTML 原文里出现（忽略空白），对不上即中止；
  4. 写 资产清单_v1.0_<日期>.md（含 sha256，便于日后校验资产未被改动）。
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re

VAR_DECL = re.compile(r'\bvar\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*([\[{])')


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def match_bracket(s, i):
    """从 s[i]（'[' 或 '{'）起做括号配平，返回闭合下标；配不平返回 -1。"""
    pairs = {'[': ']', '{': '}'}
    close = pairs[s[i]]
    depth = 0
    instr = None
    j = i
    while j < len(s):
        ch = s[j]
        if instr:
            if ch == '\\':
                j += 2
                continue
            if ch == instr:
                instr = None
        elif ch in '"\'`':
            instr = ch
        elif ch == s[i]:
            depth += 1
        elif ch in pairs.values():
            depth -= 1
            if depth == 0 and ch == close:
                return j
        j += 1
    return -1


def js_to_json(lit):
    """JS 字面量 → JSON：只做「无引号键名加引号」这一处最小转换。"""
    return re.sub(r'([{,]\s*)([A-Za-z_$][A-Za-z0-9_$]*)\s*:', r'\1"\2":', lit)


def walk_nums(node, out):
    if isinstance(node, dict):
        for v in node.values():
            walk_nums(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_nums(v, out)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        out.add(('%g' % node) if isinstance(node, float) else str(node))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--images', default='logo.png:0,hero.png:1',
                    help='按出现顺序给内联图命名，形如 名字:序号,名字:序号')
    ap.add_argument('--data-name', default='items.json')
    a = ap.parse_args()

    html = open(a.html, encoding='utf-8').read()
    os.makedirs(os.path.join(a.out_dir, '图片'), exist_ok=True)
    os.makedirs(os.path.join(a.out_dir, '数据'), exist_ok=True)

    ms = list(re.finditer(r'data:image/([a-z+]+);base64,', html))
    img_meta = []
    for pair in [p for p in a.images.split(',') if p.strip()]:
        name, idx = pair.rsplit(':', 1)
        idx = int(idx)
        if idx >= len(ms):
            raise SystemExit('图片序号 %d 超出范围（共 %d 张）' % (idx, len(ms)))
        start = ms[idx].end()
        ends = [p for p in (html.find('"', start), html.find("'", start),
                            html.find(')', start)) if p > 0]
        if not ends:
            raise SystemExit('第 %d 张图未找到 base64 结尾' % idx)
        raw = base64.b64decode(html[start:min(ends)])
        open(os.path.join(a.out_dir, '图片', name), 'wb').write(raw)
        img_meta.append({'file': '图片/' + name, 'mime': 'image/' + ms[idx].group(1),
                         'bytes': len(raw), 'sha256': sha256(raw)})
        print('IMG %s %d 字节' % (name, len(raw)))

    data, names = None, []
    for m in VAR_DECL.finditer(html):
        end = match_bracket(html, m.end() - 1)
        if end < 0:
            raise SystemExit('变量 %s 的括号未配平，无法安全提取' % m.group(1))
        lit = html[m.end() - 1:end + 1]
        try:
            val = json.loads(js_to_json(lit))
        except Exception as e:
            print('SKIP var %s（不是纯数据字面量：%s）' % (m.group(1), e))
            continue
        if data is None:
            data = {}
        data[m.group(1)] = val
        names.append(m.group(1))

    if data:
        nums = set()
        walk_nums(data, nums)
        flat = re.sub(r'\s+', '', html)
        miss = sorted(n for n in nums if n not in flat)
        if miss:
            raise SystemExit('数值回验失败：%s 在原文中未找到（反提结果不可信）' % ', '.join(miss[:8]))
        dpath = os.path.join(a.out_dir, '数据', a.data_name)
        open(dpath, 'w', encoding='utf-8').write(
            json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        print('DATA 变量 %s → %s' % (', '.join(names), dpath))
        print('数值回验通过（%d 个数值逐位命中原文）' % len(nums))
    else:
        print('未在成品里找到可提取的数据字面量')

    today = datetime.date.today().isoformat()
    lines = ['# 演示件资产清单 v1.0', '',
             '> 固化日期：%s ｜ 反提自：%s' % (today, os.path.basename(a.html)),
             '> 源件 sha256：`%s`' % sha256(html.encode('utf-8')), '',
             '## 图片资产（出件时 base64 内联）', '',
             '| 文件 | 类型 | 字节 | sha256(前16) |', '|---|---|---|---|']
    for im in img_meta:
        lines.append('| `%s` | %s | %d | `%s` |'
                     % (im['file'], im['mime'], im['bytes'], im['sha256'][:16]))
    if data:
        lines += ['', '## 数据集', '',
                  '- `数据/%s`：变量 %s' % (a.data_name, ', '.join('`%s`' % n for n in names)),
                  '- 数值反提后已逐位回验，禁止改写']
    lines += ['', '## 复用方式', '',
              '1. 图片按字节读入 → base64 内联，成品零外部依赖；',
              '2. 数据集挂到 profile 的 interaction.data 上，由出件器注入交互件模板；',
              '3. 换产品时整体替换该产品目录，技能本体不动。']
    mp = os.path.join(a.out_dir, '资产清单_v1.0_%s.md' % today)
    open(mp, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines) + '\n')
    print('清单：%s' % mp)


if __name__ == '__main__':
    main()
