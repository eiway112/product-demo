#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""演示件信息密度量化器（零第三方依赖，脚本内不得出现任何产品名）。

用法：
  python measure_density.py <成品.html> [<成品2.html> ...] [--json <out.json>]

为什么要有这个脚本：
  上一轮做量化对照的脚本放在 %TEMP%，隔日被静默清零，导致「数值数据点 = 19」
  这个基准再也复现不出来。本脚本把口径写死在代码里，可被第三方逐条复刻。

口径定义（改任何一条都必须同步改本说明，否则对照表失真）
  · 标记层文本 = 去掉 <script>/<style> 块与 HTML 注释后剩下的源码（保留标签本身）
  · 可见文本   = 标记层文本再剥标签、解实体
  · 正文中文字 = 可见文本中的 CJK 统一表意文字（U+4E00-U+9FFF）计数
  · 叙事数值   = 可见文本里的数值 token；两侧不得紧邻字母/数字/连字符/斜杠
                 （排除 GB/T 45305.2 这类标准号片段与型号串）；排除 19xx/20xx 年份
  · 全文件数值 = 同上，但统计范围含 <script>/<style>（即把交互件数据集也算进去）
  · 交互件数   = id="ix-body" 出现次数（交互件契约 C2）。契约确立前产出的旧成品
                 用的是旧前缀，此处必然为 0，报告里标注为「旧版不可比」
  · 五要件齐备度 = 是否存在 data-role 为 pain/method/evidence/diff/boundary 的 section，
                   以及是否声明了 gap 段。旧成品无 data-role，同样为「旧版不可比」

**本文件是「文本口径」与「词条匹配」的单一事实来源**：check_demo.py 与 audit_body.py 都从这里
取实现，不许再各抄一份。这条不是洁癖：visible_text 曾经在两处各有一份实现，一边剥 HTML 注释、
一边不剥，注释里却都写着「同口径」——同一口径两份实现，漂移只是时间问题。
"""
import argparse
import json
import re
import sys

CJK = re.compile(r'[\u4e00-\u9fff]')
NUM = re.compile(r'(?<![A-Za-z0-9_\-/])\d+(?:\.\d+)?(?![A-Za-z0-9_\-/])')
YEAR = re.compile(r'^(?:19|20)\d\d$')
ROLES = ('pain', 'method', 'evidence', 'diff', 'boundary')
_ENTITIES = (('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' '),
             ('&quot;', '"'), ('&#39;', "'"))


def strip_blocks(html):
    """去掉 script / style 块——两种文本口径的共同第一步。"""
    t = re.sub(r'(?s)<script\b.*?</script\s*>', ' ', html)
    return re.sub(r'(?s)<style\b.*?</style\s*>', ' ', t)


def strip_comments(t):
    """去掉 HTML 注释。注释里的文字不是给读者看的内容，计入会把密度注水文抬高。"""
    return re.sub(r'(?s)<!--.*?-->', ' ', t)


def markup_text(html):
    """标记层文本：去 script/style 块与注释，**保留标签本身**。

    「按源码计数」型判据（数 <h3> / 数 id="ix-body" / 按容器取内容）必须用它，不能拿全文数——
    交互件的数据是内联在 <script> 里的 JSON，而 item 的 note 字段允许内联 HTML 标签；
    一旦数据里出现 '<h3>' 或 'id="ix-body"' 字面量，计数值就被数据本身污染，
    方向可能是假红也可能是假绿。
    """
    return strip_comments(strip_blocks(html))


def visible_text(html):
    """可见文本：标记层文本再剥标签、解实体。"""
    t = re.sub(r'<[^>]+>', ' ', markup_text(html))
    for a, b in _ENTITIES:
        t = t.replace(a, b)
    return t


def strip_js_comments(code):
    """剥 JS 的行注释与块注释，且不误伤字符串字面量。

    判「IX_init() 有没有被调用」前必须先剥注释：被注释掉的调用在源码里长得和真调用一样。
    不能只用正则删 `//…` 与 `/*…*/`——URL（https://…）自带 `//`，字符串里也可能出现注释符号，
    所以这里按字符扫描，遇到引号就整段跳过字符串。
    """
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c in '"\'`':
            q, j = c, i + 1
            while j < n:
                if code[j] == '\\':
                    j += 2
                    continue
                if code[j] == q:
                    j += 1
                    break
                j += 1
            out.append(code[i:j])
            i = j
        elif c == '/' and i + 1 < n and code[i + 1] == '/':
            j = code.find('\n', i)
            i = n if j < 0 else j
        elif c == '/' and i + 1 < n and code[i + 1] == '*':
            j = code.find('*/', i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def word_regex(word):
    """把一个词条编译成正则；返回 None 表示按朴素子串匹配（中文等没有词边界的文字）。

    三条设定都有代价，理由如下——
    · **允许数字后缀**：产品词在真实文案里最常见的形态是「产品代号 + 型号数字」。
      旧实现的右边界含 `[A-Za-z0-9_]`，于是这种形态永远命中不了，白丢一大半判别力。
      这里改成左边界严格、右侧允许跟一串数字。
    · **多词词条允许空格 / 连字符 / 下划线连接**：同一厂商名常被写成 `Foo-Bar Studio` 或 `FooBarStudio`。
    · **`re:` 前缀支持正则条目**：用来表达「代号 + 变体后缀」这类字面匹配说不清的形态。
      注意：词表不随库入库（见 SKILL.md 已知坑），本体里永远不写死产品名——
      检查定义与被检查内容必须分开，否则扫描器自己就成了本体里最后一处产品名。
    """
    w = word.strip()
    if w.startswith('re:'):
        return re.compile(w[3:].strip())
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9_\-]*', w):
        return re.compile(r'(?<![A-Za-z0-9_])' + re.escape(w) + r'\d*(?![A-Za-z_])')
    if re.fullmatch(r'[A-Za-z0-9_\- ]+', w) and re.search(r'[A-Za-z]', w):
        parts = [re.escape(p) for p in w.split()]
        return re.compile(r'(?<![A-Za-z0-9_])' + r'[\s\-_]*'.join(parts) + r'(?![A-Za-z0-9_])')
    return None


def word_hit(text, word):
    """词条是否命中：ASCII 走词边界，其余走子串。"""
    rx = word_regex(word)
    return (rx.search(text) is not None) if rx else (word in text)


def nums(text):
    return [n for n in NUM.findall(text) if not YEAR.match(n)]


def measure(path):
    raw = open(path, 'rb').read()
    html = raw.decode('utf-8', 'replace')
    vis = visible_text(html)
    vnums = nums(vis)
    anums = nums(html)
    roles = re.findall(r'data-role\s*=\s*"([^"]*)"', html)
    legacy = not roles
    return {
        '文件': path.replace('\\', '/').split('/')[-1],
        '字节': len(raw),
        'h1': len(re.findall(r'<h1[\s>]', html)),
        'h2': len(re.findall(r'<h2[\s>]', html)),
        'h3': len(re.findall(r'<h3[\s>]', html)),
        'h4': len(re.findall(r'<h4[\s>]', html)),
        'section': len(re.findall(r'<section[\s>]', html)),
        'img': len(re.findall(r'<img[\s>]', html)),
        '正文中文字': len(CJK.findall(vis)),
        '叙事数值唯一': len(set(vnums)),
        '叙事数值出现': len(vnums),
        '全文件数值唯一': len(set(anums)),
        '交互件数': len(re.findall(r'id="ix-body"', html)),
        'data-role 段数': len(roles),
        '五要件': '旧版不可比' if legacy else ''.join(
            (k[0].upper() if k in roles else '-') for k in ROLES),
        'gap 段': '旧版不可比' if legacy else ('有' if 'gap' in roles else '无'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('htmls', nargs='+')
    ap.add_argument('--json')
    a = ap.parse_args()

    rows = [measure(p) for p in a.htmls]
    keys = list(rows[0].keys())
    for r in rows:
        print('===== %s' % r['文件'])
        for k in keys[1:]:
            print('  %-8s %s' % (k, r[k]))
    if len(rows) > 1:
        print('\n===== 横向对照')
        print('  ' + ' | '.join(['指标'] + [r['文件'][:12] for r in rows]))
        for k in keys[1:]:
            print('  ' + ' | '.join([k] + [str(r[k]) for r in rows]))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print('\n已写出：%s' % a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
