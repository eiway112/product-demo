#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""演示件判据核验器（零第三方依赖，脚本内不得出现任何产品名）。

用法：
  python check_demo.py <html> [--profile <profile.json>] [--data <数据源.json>]
                       [--img N] [--js-value S] [--chrome <chrome.exe>]
                       [--shot <out.png>] [--r1 "词条1,词条2"] [--json <report.json>]
                       [--expect pass=23,fail=0,skip=2] [--self-test] [--deliver <落盘路径>]

判据分三层：
  · 结构层 B/V —— 单文件、自包含、打得开。判的是「不许出什么问题」，属上限型。
  · 叙事层 N   —— 五要件（痛点 / 方法 / 实证 / 差异 / 边界）是否齐备且不空壳。
                  为什么补这一层：上限型只能证明「没写错」，证明不了「说清楚了」——
                  一份只剩标题的空壳页，在上限型判据下是全绿的。
  · 交互层 I   —— 交互件硬契约（assets/interaction_patterns.md §三）是否真正落地。

离线判据：B1 B2 B3 B4 B6 B7 B8 V1 V2 V4 N1 N2 N3 N4 N5 I1 I2 I3
浏览器判据（需 --chrome）：B5 V3 V5 V7 V8
元判据（判这座闸门自身，与被判的东西不同层）：R1 U1 U2 D1–D5

三条元判据的作用是把「缺件」与「查过」分开，它们只对下面这些历史故障负责：
  · U1 出席检查 —— 每条登记过的判据本次都必须产出结论行。V3/V7 曾经整段静默消失、
    V2 在成品无图时也一行不出，两边都被读成「查过且干净」。有了登记表 + U1，这类
    「既不 PASS 也不 SKIP」的漏洞一次性堵死，以后新加判据忘了在某个分支出结论也一样会被抓。
  · U2 期望契约 —— `--expect` 把文档里的数字（"PASS 23 / SKIP 2"）变成机器可判的契约。
    此前这些数字只存在于 README 的表格里，没有任何东西在看，漂移到 PASS 5 也没人知道。
  · D1–D5 落盘闸门 —— `--deliver` 校验交付链最后一公里（命名 / 一致性 / git 兜底）。

退出码：0 = 无 FAIL；1 = 存在 FAIL。SKIP = 判据因缺省条件未执行，不算通过。
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 文本口径、词条匹配与量化器共用一份实现——两处各写一遍必然漂移
from measure_density import (CJK, markup_text, nums, strip_js_comments,  # noqa: E402
                             strip_comments, visible_text, word_hit)

MB = 1024 * 1024
PLACEHOLDER = re.compile(r'__(?:[A-Z][A-Z0-9_]{2,})__')

# B6 本机绝对路径。**先剥 URL 再匹配**（见 strip_urls）：
# 旧实现直接拿 `(?:[A-Za-z]:[\\/])` 扫全文，命中 https:// 里的 "s:/" —— 正文里放一句普通网址
# 就被判成本机路径（假红）。假红不是小事：它把这条判据的真实语义（"成品里不许焊死作者机器的路径"）
# 淹掉了，而与此同时真正的 CSS 外链却在别处漏着。
# 识别：盘符路径 C:\ / C:/；UNC \\srv\share；POSIX 家目录与常见绝对路径根。
# 不识别：相对路径、单段的 Unix 文件名、`/foo/bar` 这类无法确定是不是本机的路径（刻意留白，
# 避免把正常相对链接误判成本机路径）。识别范围变了必须同步改这段注释。
ABS_PATH = re.compile(
    r'(?:[A-Za-z]:[\\/])'
    r'|(?:\\\\[^\s"\'<>\\]+(?:\\|\b))'
    r'|(?:/(?:Users|home|tmp|var|opt|srv|Applications)/)'
)
URL_TOKEN = re.compile(r'(?i)\b(?:https?|ftp|file):[\\/]{0,2}[^\s"\'<>\\)]+')
PROTO_REL_ATTR = re.compile(r'(?i)(?:src|href|srcset|action|formaction)\s*=\s*"?//[^\s"<>]*')
# url() / @import / srcset 里的远程地址：漏掉它们，"零外部依赖" 只保住了 HTML 属性那一层，
# 而 `@import url("//evil.example.com/a.css")` 能让成品在断网环境下一片空白。
CSS_URL = re.compile(r'(?i)url\(\s*["\']?([^"\')]+)["\']?\s*\)')
CSS_IMPORT = re.compile(r'(?i)@import\s+["\']([^"\']+)["\']')
REF_ATTRS = re.compile(r'(?i)\b(?:src|href|srcset|poster|action|formaction)\s*=\s*"([^"]+)"')

# ------------------------------------------------------------- 判据登记表
# 每条判据必须在此登记，不许只在某个函数里默默 reach 出来。登记表服务于三件事：
#   ① U1 出席检查：跑完逐条对照，没出结论行的直接 FAIL；
#   ② U2 期望契约：让外部能用 --expect 断言总数；
#   ③ negative_test 的注入覆盖率：本次参数下跑得到、却没有注入用例的判据要被点名。
# 第二列是该判据**需要哪些调用参数**才可能执行（空元组 = 离线即可判）。
CRITERIA = (
    ('B1', ()), ('B2', ()), ('B3', ()), ('B4', ()), ('B5', ('chrome',)),
    ('B6', ()), ('B7', ()), ('B8', ()),
    ('V1', ()), ('V2', ()), ('V3', ('chrome', 'js_value')), ('V4', ()),
    ('V5', ('chrome',)), ('V7', ('chrome', 'shot')), ('V8', ('chrome',)),
    # V9 是后来补的（关键数字回指）。编号跳过 V6：本仓已用「V6」指代 negative_test
    # 这个脚本本身（SKILL.md「V6 负向测试是核心」），判据号不与脚本代称撞名。
    ('V9', ()),
    ('N1', ()), ('N2', ()), ('N3', ()), ('N4', ()), ('N5', ()),
    ('I1', ()), ('I2', ()), ('I3', ()), ('I4', ()),
    ('R1', ()),
)
CRITERIA_ARGS = dict(CRITERIA)
# 哪些判据不靠 HTML 注入证明会失败，而靠 --self-test 里的纯函数单测证明。
# V7 曾在这里：它判 Chrome 产出的 PNG，「头与尺寸」确实注入动不了。但补上像素校验后，
# 一条把可见内容整体藏掉的 CSS 注入就能让截图变纯色——HTML 注入动得了它了，
# 于是拉出豁免，改由 negative_test 的空白页注入证明。列表留空：以后再有
# 注入真动不了的判据才往里放，不许为省事预先豁免。
UNIT_PROVEN = set()


def strip_urls(t):
    """把 URL 换成空格——B6 判本机路径前必须先做这一步。"""
    return PROTO_REL_ATTR.sub(' ', URL_TOKEN.sub(' ', t))


def external_refs(html):
    """收集成品里所有会触发外部请求的地址：HTML 属性 + CSS 层的 url()/@import。

    只扫 src/href 属性是不够的：`@import url("//x/a.css")`、`background:url(//x/b.png)`、
    `srcset="https://x/y.png 2x"` 全都会联网，而它们在 src/href 里一个字都不出现。
    """
    out = []
    for v in REF_ATTRS.findall(html):
        for piece in v.split(','):
            out.append(piece.strip().split(' ', 1)[0])
    for blk in re.findall(r'(?s)<style\b.*?</style\s*>', html):
        out += CSS_IMPORT.findall(blk)
        out += CSS_URL.findall(blk)
    for v in re.findall(r'(?i)style\s*=\s*"([^"]*)"', html):
        out += CSS_URL.findall(v)
    ext = []
    for u in out:
        u = u.strip().strip('\'"')
        if not u or u.startswith('#') or u.startswith('data:'):
            continue
        if u.startswith('http://') or u.startswith('https://') or u.startswith('//'):
            ext.append(u)
    return ext

# ---------------------------------------------------------------- 判据参数
# 以下每个数字都要能指出依据，不接受拍脑袋。改数字必须同步改这里的注释。

NARRATIVE_ROLES = ('pain', 'method', 'evidence', 'diff', 'boundary')
ROLE_CN = {'pain': '痛点', 'method': '方法', 'evidence': '实证',
           'diff': '差异', 'boundary': '边界'}

# N2 要件非空壳的文本下限：一个要件至少要说清「是什么 + 为什么」，
# 两句完整的话约 40 字。新管线成品实测最低要件 100+ 字，此处留 60% 余量。
MIN_ROLE_CJK = 40

# N2 的内容块白名单：只认语义块，不认 div——div 太宽，任何版式都有，能过等于没判。
CONTENT_BLOCK = re.compile(r'<(?:p|table|ul|ol|li|h3|h4|h5|h6|figure|blockquote|dl)\b', re.I)

# N5 全篇文本密度下限。依据：新管线成品实测正文中文字 914，留 23% 余量。
MIN_TOTAL_CJK = 700

# N5 数值密度分档：按交互形态分，不按产品分。
#   文本密度下限与形态无关（叙事本身的要求）；
#   数值密度只在计算型上要求——能力型产品没有算子，强求数值密度只会逼出造数据。
# 依据：计算型成品实测叙事数值唯一 32，取 25% 作退化警戒线。
BUDGET_NUMERIC = {
    'calculator': 8,
    'catalog': 0,
}


def read_text(p):
    return open(p, encoding='utf-8').read()


def attr_of(attrs, key):
    m = re.search(r'%s\s*=\s*"([^"]*)"' % re.escape(key), attrs)
    return m.group(1) if m else ''


def section_blocks(html):
    """切出 (属性串, 内部 HTML)。本体的 section 契约不嵌套，非贪婪足够。"""
    return [(m.group(1), m.group(2))
            for m in re.finditer(r'(?s)<section\b([^>]*)>(.*?)</section>', html)]


def extract_var_literal(html, name):
    """取 `var NAME = <数组或对象字面量>` 的字面量原文；取不到返回 None。

    用括号配平而非非贪婪正则：字面量里必然还有嵌套的 [] 与 {}，
    非贪婪会在第一个内层括号处就截断。
    """
    m = re.search(r'\bvar\s+%s\s*=\s*' % re.escape(name), html)
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] not in '[{':
        return None
    op = html[i]
    cl = ']' if op == '[' else '}'
    depth, in_str, esc, j = 0, False, False, i
    while j < len(html):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                return html[i:j + 1]
        j += 1
    return None


def img_checks(html, expect_img):
    """返回 (ok_list, skip_list, fail_list)。B2 / V2。"""
    ok, skip, fail = [], [], []
    srcs = re.findall(r'<img[^>]*\ssrc="([^"]*)"', html)
    if expect_img is None:
        skip.append('B2 未指定 --img，不判张数（本次只判「全部内联」）')
    elif len(srcs) == expect_img:
        ok.append('B2 img 数 = %d，与契约一致' % expect_img)
    else:
        fail.append('B2 img 数 %d ≠ 契约 %d' % (len(srcs), expect_img))
    bad = [s for s in srcs if not s.startswith('data:image/')]
    if bad:
        fail.append('B2 存在 %d 张非内联图' % len(bad))
    elif srcs:
        ok.append('B2 全部图片 data: 内联')
    # V2：逐张解码并读真实像素尺寸
    sizes = []
    for i, s in enumerate(srcs):
        b64 = s.split(',', 1)[1] if ',' in s else ''
        try:
            raw = base64.b64decode(b64)
        except Exception as e:
            fail.append('V2 第 %d 张 base64 解码失败：%s' % (i + 1, e))
            continue
        if raw[:8] == b'\x89PNG\r\n\x1a\n':
            w, h = struct.unpack('>II', raw[16:24])
        elif raw[:2] == b'\xff\xd8':
            w, h = -1, -1  # JPEG 不解析，能解码即视为通过
        else:
            fail.append('V2 第 %d 张不是 PNG/JPEG' % (i + 1))
            continue
        if w == 0 or h == 0:
            fail.append('V2 第 %d 张尺寸为 0（未真正解码）' % (i + 1))
        else:
            sizes.append((w, h))
    if sizes and not [f for f in fail if f.startswith('V2')]:
        ok.append('V2 %d 张图全部解码成功（尺寸 %s）'
                  % (len(sizes), ','.join('%dx%d' % s for s in sizes)))
    elif not srcs:
        # 一张图都没有时，旧实现既不出 PASS 也不出 SKIP——整条判据静默消失，
        # 于是「本次没验图片」被读成「图片验过了」。按本仓自己的三态语义列 SKIP。
        skip.append('V2 无可判对象：成品无内联图，未验证任何图片的解码（不计入通过）')
    return ok, skip, fail


def _walk_numbers(node, out):
    """收集数据源里的全部数值标量。

    原先这里限定了一组字段名（某个产品的算例字段），等于把那个产品的数据结构
    焊进判据脚本——本轮把它拆掉，改成「数据源里所有数值都得在成品里能找到」。
    """
    if isinstance(node, bool):
        return
    if isinstance(node, dict):
        for v in node.values():
            _walk_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_numbers(v, out)
    elif isinstance(node, (int, float)):
        out.add(('%g' % node) if isinstance(node, float) else str(node))


def value_checks(html, data_path):
    """V4：成品内联数据集必须与数据源逐项一致。

    变量名取交互件契约里的固定名 IX_ITEMS / IX_AXIS，与具体产品无关。
    """
    ok, skip, fail = [], [], []
    if not data_path:
        return ok, ['V4 未提供数据源，跳过'], fail
    try:
        data = json.loads(read_text(data_path))
    except Exception as e:
        return ok, skip, ['V4 数据源解析失败：%s' % e]

    lit = extract_var_literal(html, 'IX_ITEMS')
    if lit is not None:
        try:
            inline = json.loads(lit)
        except Exception as e:
            fail.append('V4 成品内联数据集解析失败：%s' % e)
            inline = None
        if inline is not None:
            src = data.get('items', data.get('cases', data))
            if inline == src:
                ok.append('V4 内联数据集与数据源逐项一致（%d 条）' % len(inline))
            else:
                fail.append('V4 内联数据集与数据源不一致：%s' % _first_diff(src, inline))
        axis = data.get('axis') or {}
        if axis:
            alit = extract_var_literal(html, 'IX_AXIS')
            got = None
            if alit:
                try:
                    got = json.loads(alit)
                except Exception:
                    got = None
            want = [axis.get('lo'), axis.get('hi')]
            if got is None:
                fail.append('V4 未取到区间轴 IX_AXIS')
            elif got != want:
                fail.append('V4 区间轴不一致：成品 %s ≠ 数据源 %s' % (got, want))
            else:
                ok.append('V4 区间轴一致（%s）' % got)
        return ok, skip, fail

    # 兜底：成品里取不到内联数据集时，数据源数值必须逐字符出现
    numsrc = set()
    _walk_numbers(data, numsrc)
    if not numsrc:
        return ok, ['V4 数据源无关键数值字段，跳过'], fail
    miss = sorted(n for n in numsrc if n not in html)
    if miss:
        fail.append('V4 数据源数值在成品中缺失：%s' % ', '.join(miss[:8]))
    else:
        ok.append('V4 %d 个关键数值与数据源逐字符一致（%s）'
                  % (len(numsrc), ', '.join(sorted(numsrc)[:8])))
    return ok, skip, fail


def stats_checks(html, content_path):
    """V9：关键数字区的数值必须能回指到 content.json。

    这一块是成品里唯一「内容会膨胀却无出处判据」的地方：数字带最容易被读成承诺
    （「12 个技能」），而它此前只靠人眼确认与 items.json 自洽。数据源是 content.json
    的 stats，不是交互件数据集——V4 那条覆盖不到它。
    """
    ok, skip, fail = [], [], []
    # 成品里的数字带：骨架渲染成 <div class="stats"> … <div class="stat"><b>数值</b>
    blocks = re.findall(r'(?s)<div[^>]*class="[^"]*\bstats\b[^"]*"[^>]*>(.*?)</div>\s*</div>',
                        html)
    shown = []
    for b in blocks:
        shown += re.findall(r'(?s)<b[^>]*>\s*([0-9][0-9,\.]*)\s*</b>', b)
    if not shown:
        # 成品没渲染数字带时，若配置里声明了 stats，那才是问题（整块被静默吃掉）
        if content_path and os.path.isfile(content_path):
            try:
                c = json.loads(read_text(content_path))
            except Exception:
                c = {}
            if c.get('stats'):
                fail.append('V9 content.json 声明了 %d 条 stats，成品里却没有渲染出数字带——'
                            '关键数字被静默丢掉' % len(c['stats']))
                return ok, skip, fail
        return ok, ['V9 本次无关键数字区（成品未渲染 stats），未执行'], fail

    if not content_path or not os.path.isfile(content_path):
        fail.append('V9 成品渲染了 %d 个关键数字（%s），却取不到 content.json 回指——'
                    '数字带必须有出处' % (len(shown), ', '.join(shown[:5])))
        return ok, skip, fail
    try:
        c = json.loads(read_text(content_path))
    except Exception as e:
        return ok, skip, ['V9 content.json 解析失败：%s' % e]

    src = c.get('stats') or []
    allowed = set()
    for st in src:
        if isinstance(st, dict) and 'value' in st:
            v = st['value']
            allowed.add(('%g' % v) if isinstance(v, float) else str(v))
    if not allowed:
        fail.append('V9 成品有 %d 个关键数字，但 content.json 的 stats 为空——'
                    '这些数字没有出处' % len(shown))
        return ok, skip, fail
    orphan = [n for n in shown if n not in allowed]
    if orphan:
        fail.append('V9 关键数字无出处：成品里的 %s 在 content.json 的 stats 中找不到'
                    % ', '.join(sorted(set(orphan))[:5]))
    else:
        ok.append('V9 %d 个关键数字全部回指 content.json 的 stats（%s）'
                  % (len(shown), ', '.join(sorted(set(shown))[:6])))
    return ok, skip, fail


def _first_diff(src, dst, path=''):
    """返回第一处不一致的可读位置。"""
    if isinstance(src, dict) and isinstance(dst, dict):
        for k in src:
            if k not in dst:
                return '%s.%s 缺失' % (path, k)
            d = _first_diff(src[k], dst[k], '%s.%s' % (path, k))
            if d:
                return d
        for k in dst:
            if k not in src:
                return '%s.%s 多出' % (path, k)
        return ''
    if isinstance(src, list) and isinstance(dst, list):
        if len(src) != len(dst):
            return '%s 条数 %d≠%d' % (path, len(src), len(dst))
        for i, (a, b) in enumerate(zip(src, dst)):
            d = _first_diff(a, b, '%s[%d]' % (path, i))
            if d:
                return d
        return ''
    if src != dst:
        return '%s 值 %r≠%r' % (path, src, dst)
    return ''


def narrative_checks(html, prof):
    """N1–N5：叙事五要件。只认 data-role，不认内容怎么写——产品差异不在这层。"""
    ok, skip, fail = [], [], []
    secs = section_blocks(html)
    # 计数型判据一律作用在标记层文本上（去 script/style 块与注释）：
    # 交互件数据是内联 JSON，里面出现 '<h3>' 或 'id="ix-body"' 字面量是允许的
    # （item 的 note 字段就允许内联标签），拿全文数会被数据本身污染。
    markup = markup_text(html)
    by_role, declared_gap = {}, set()
    for attrs, inner in secs:
        r = attr_of(attrs, 'data-role')
        if not r:
            continue
        by_role.setdefault(r, []).append((attrs, inner))
        if r == 'gap':
            g = attr_of(attrs, 'data-gap-for')
            if g:
                declared_gap.add(g)

    # ---- N1 五要件覆盖 ----
    missing = [r for r in NARRATIVE_ROLES if r not in by_role and r not in declared_gap]
    if not secs:
        fail.append('N1 没有任何 data-role="..." 的 section —— 五要件一个都没落地')
    elif missing:
        fail.append('N1 五要件缺 %d 件且未声明 gap：%s'
                    % (len(missing), ', '.join('%s(%s)' % (r, ROLE_CN[r]) for r in missing)))
    else:
        tail = ('，其中 %d 件已按 data-role="gap" 显式声明为「本产品无此类证据」'
                % len(declared_gap)) if declared_gap else ''
        ok.append('N1 五要件覆盖齐备（%d 个 section）%s' % (len(secs), tail))

    # ---- N2 要件非空壳（带 ix-body 的段实质内容是交互件，交给 I 组）----
    thin, hollow = [], []
    for r in NARRATIVE_ROLES:
        for _attrs, inner in by_role.get(r, []):
            if 'id="ix-body"' in inner:
                continue
            n = len(CJK.findall(visible_text(inner)))
            if n < MIN_ROLE_CJK:
                thin.append('%s(%d 字)' % (r, n))
            elif not CONTENT_BLOCK.search(inner):
                hollow.append(r)
    if thin:
        fail.append('N2 要件内容过薄（<%d 字）：%s —— 只有标题的要件等于没写'
                    % (MIN_ROLE_CJK, ', '.join(thin)))
    if hollow:
        fail.append('N2 要件没有内容块（p/table/ul/h3/h4 至少一个）：%s' % ', '.join(hollow))
    if not thin and not hollow:
        ok.append('N2 各要件均非空壳（≥%d 字且含内容块）' % MIN_ROLE_CJK)

    # ---- N3 gap 与交互件互斥 ----
    ix_count = len(re.findall(r'id="ix-body"', markup))
    if declared_gap and ix_count:
        fail.append('N3 已声明 gap（%s）却仍留着 %d 个交互件 —— 缺件时硬凑空件比没有件更糟'
                    % (', '.join(sorted(declared_gap)), ix_count))
    else:
        ok.append('N3 gap 与交互件互斥成立（gap %d 件 / 交互件 %d 个）'
                  % (len(declared_gap), ix_count))

    # ---- N4 层级下限 ----
    h1 = len(re.findall(r'<h1[\s>]', markup))
    h3 = len(re.findall(r'<h3[\s>]', markup))
    h4 = len(re.findall(r'<h4[\s>]', markup))
    if h1 != 1:
        fail.append('N4 h1 数 = %d，必须恰好 1' % h1)
    else:
        ok.append('N4 h1 = 1')
    if h3 + h4 < 2:
        fail.append('N4 子标题不足（h3+h4 = %d < 2）—— 叙事退化成了平铺文本' % (h3 + h4))
    else:
        ok.append('N4 子标题 h3=%d h4=%d（≥2）' % (h3, h4))

    # ---- N5 密度分档 ----
    vis = visible_text(html)
    cjk = len(CJK.findall(vis))
    if cjk < MIN_TOTAL_CJK:
        fail.append('N5 正文中文字 %d < %d —— 页面没把事说清楚' % (cjk, MIN_TOTAL_CJK))
    else:
        ok.append('N5 正文中文字 %d ≥ %d' % (cjk, MIN_TOTAL_CJK))
    pattern = ((prof or {}).get('interaction') or {}).get('pattern') or ''
    if not pattern:
        skip.append('N5 数值密度：未提供 profile（或未声明 interaction.pattern），不判分档')
    elif pattern not in BUDGET_NUMERIC:
        fail.append('N5 数值密度：pattern=%s 未在分档表登记 —— 新增交互形态必须先定阈值' % pattern)
    else:
        need = BUDGET_NUMERIC[pattern]
        got = len(set(nums(vis)))
        if not need:
            ok.append('N5 %s 形态不设数值密度下限（无算式可对照，强求会逼出造数据），实测唯一 %d'
                      % (pattern, got))
        elif got < need:
            fail.append('N5 叙事数值唯一 %d < %d（%s 形态的结论就是数值，密度不足＝没给实证）'
                        % (got, need, pattern))
        else:
            ok.append('N5 叙事数值唯一 %d ≥ %d（%s）' % (got, need, pattern))
    return ok, skip, fail


def interaction_checks(html, prof):
    """I1–I3：交互件硬契约落地。对应 interaction_patterns.md §三 的 C1–C4。

    §三 一共 6 条硬契约，本函数只判其中 C1–C4——因为它们判的都是**成品**。
    C5 与 C6 判的都是**模板本体**，不是成品，所以都不在这里：
      · C5（模板可见文本不得含中文）由 audit_body.py 的 C5 族在提交前扫描模板；
      · C6（模板必须提供 V3 取证锚点 data-ix-ready）由 V3 在实际调用时验证，
        调用方传 `--js-value IXRDY` 即可（值由模板用拼接写法生成，源码里无连续字面量）。
    **只跑 check_demo 且不给 --js-value 时，C5 与 C6 都得不到验证——它们会列 SKIP，不装绿。**
    """
    ok, skip, fail = [], [], []
    pattern = ((prof or {}).get('interaction') or {}).get('pattern') or ''
    markup = markup_text(html)
    if 'id="ix-body"' not in markup:
        if pattern:
            fail.append('I1 profile 声明了 interaction.pattern=%s，成品里却没有 id="ix-body"'
                        % pattern)
        else:
            skip.append('I1/I2/I3 成品无交互件（gap 形态，交互契约不适用）')
        return ok, skip, fail

    # I1 主输出容器 + 默认态（C2）
    m = re.search(r'<[^>]*id="ix-body"[^>]*>(.*?)</', markup, re.S)
    if not m:
        fail.append('I1 取不到 id="ix-body" 的初始内容')
    else:
        init = visible_text(m.group(1)).strip()
        if init == '—':
            ok.append('I1 id="ix-body" 初始态为 —（默认态可被判定）')
        else:
            fail.append('I1 id="ix-body" 初始内容为 %r，应为 —（没有默认态的交互件等于空白件）'
                        % init[:20])

    # I2 初始化函数定义并调用（C3）
    # 必须先剥掉 JS 注释：否则「// IX_init();」或「/* IX_init(); */」这种被注释掉的调用
    # 仍会被当成有效调用。第一条是负向测试抓出来的；第二条是同一个坑的另一半——
    # 只剥行注释时，块注释版的注入照样报绿，而负向注入恰巧也用行注释，两者同构互相掩护。
    code = strip_js_comments(strip_comments(html))
    defs = len(re.findall(r'function\s+IX_init\s*\(', code))
    calls = len(re.findall(r'(?m)^[ \t]*IX_init\s*\(\s*\)\s*;', code))
    if not defs:
        fail.append('I2 未定义 IX_init()')
    elif not calls:
        fail.append('I2 定义了 IX_init() 但从未调用（或调用被注释掉了）—— 默认态不会渲染')
    else:
        ok.append('I2 IX_init() 已定义并调用（定义 %d 处 / 调用 %d 处）' % (defs, calls))

    # I3 数据契约（C1 + C4 + item 结构）
    lit = extract_var_literal(html, 'IX_ITEMS')
    if lit is None:
        fail.append('I3 取不到交互件数据变量 IX_ITEMS')
        return ok, skip, fail
    try:
        items = json.loads(lit)
    except Exception as e:
        fail.append('I3 IX_ITEMS 解析失败：%s' % e)
        return ok, skip, fail
    if not isinstance(items, list):
        fail.append('I3 IX_ITEMS 不是数组')
        return ok, skip, fail

    if len(items) < 2:
        fail.append('I3 数据项数 %d < 2 —— 1 条数据点与不点看不出差别' % len(items))
    else:
        ok.append('I3 数据项数 %d ≥ 2' % len(items))
    bad = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            bad.append('第%d项不是对象' % (i + 1))
            continue
        for f in ('key', 'title', 'body'):
            if not str(it.get(f) or '').strip():
                bad.append('第%d项缺 %s' % (i + 1, f))
        ms = it.get('metrics')
        if not isinstance(ms, list) or not ms:
            bad.append('第%d项 metrics 缺失或为空' % (i + 1))
            continue
        for j, mm in enumerate(ms):
            if not isinstance(mm, dict):
                bad.append('第%d项第%d条指标不是对象' % (i + 1, j + 1))
                continue
            if not str(mm.get('label') or '').strip() or not str(mm.get('value') or '').strip():
                bad.append('第%d项第%d条指标缺 label/value' % (i + 1, j + 1))
            lo, hi = mm.get('lo'), mm.get('hi')
            if (lo is None) != (hi is None):
                bad.append('第%d项第%d条 lo/hi 未成对' % (i + 1, j + 1))
            elif isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
                bad.append('第%d项第%d条 lo > hi' % (i + 1, j + 1))
    if bad:
        fail.append('I3 数据契约违规：%s' % '；'.join(bad[:6]))
    else:
        ok.append('I3 数据契约逐项通过（key/title/body/metrics 齐备、lo-hi 成对）')

    # I4 装配位置：profile 声明的 position 必须与成品里交互件所在的次序一致。
    # inline 分支此前在仓内没有任何可跑输入（四份配置无一声明 position），属于
    # 「有代码、从未被走过」的分支。补了样例还不够——还得有判据证明它真的插在原位，
    # 否则 inline 与 front 出同一份件也不会有人发现。
    pos = str(((prof or {}).get('interaction') or {}).get('position') or 'front').lower()
    idx = None
    for i, (_attrs, inner) in enumerate(section_blocks(html)):
        if 'id="ix-body"' in inner:
            idx = i
            break
    if idx is None:
        skip.append('I4 取不到交互件所在的 section，装配位置本次未验证')
    elif pos == 'front':
        if idx == 0:
            ok.append('I4 装配位置与声明一致：front —— 交互件是第 1 个分节（先玩后读）')
        else:
            fail.append('I4 声明 front，成品里交互件却排在第 %d 个分节（应在第 1 个）'
                        % (idx + 1))
    else:
        if idx > 0:
            ok.append('I4 装配位置与声明一致：%s —— 交互件在第 %d 个分节（按标记原位插入）'
                      % (pos, idx + 1))
        else:
            fail.append('I4 声明 %s，成品里交互件却排在第 1 个分节——'
                        '标记位被当成 front 处理了' % pos)
    return ok, skip, fail



# B5 的错误捕获探针。Chrome 的 --enable-logging 把 console.log / warn / error 一律打成同一
# 级别（INFO:CONSOLE），从日志里分不出错误——所以改从页面内部收集：探针注入副本的 <head>
# 之后（必须最早执行），把 console.error、未捕获异常、未处理的 Promise rejection 记进 DOM，
# 跑完再读出来。写入时机放在 load 之后 1.5s，否则读不到异步抛出的错误。原成品一字不动。
B5_PROBE = (
    '<script>/*B5PROBE*/'
    '(function(){var E=[];'
    'window.addEventListener("error",function(e){E.push("ERR:"+(e.message||""))},true);'
    'window.addEventListener("unhandledrejection",'
    'function(e){E.push("REJ:"+String(e.reason))});'
    'var ce=window.console.error,cw=window.console.warn;'
    'window.console.error=function(){E.push("CE:"+Array.prototype.join.call(arguments," "));'
    'ce.apply(console,arguments)};'
    'window.console.warn=function(){E.push("CW:"+Array.prototype.join.call(arguments," "));'
    'cw.apply(console,arguments)};'
    'window.addEventListener("load",function(){setTimeout(function(){'
    'var t=document.createElement("h1");t.id="b5probe";'
    't.textContent="ERRN:"+E.length+"|"+E.join(" ;; ");'
    'document.body.appendChild(t)},1500)});'
    '})();</script>')


def probe_copy(raw, probe, name, tmpdir=None):
    """把探针插到指定位置落一份副本，返回副本路径；找不到插入位返回 None。

    只用副本做测量，原成品一字不动（与 V5 的溢出探针同一思路）。
    副本落在**一次一议的唯一子目录**（mkdtemp）——旧实现用固定文件名落在系统临时目录，
    两次并行或一次中断残留就会互相覆盖，探针值读到的是别人那一份。
    """
    m = re.search(r'<head[^>]*>', raw, re.I)
    ins_at, ins_body = (m.end(), probe) if m else (None, None)
    if ins_at is None:
        j = raw.rfind('</body>')
        if j < 0:
            return None
        ins_at, ins_body = j, probe
    d = tmpdir or tempfile.mkdtemp(prefix='pd_probe_')
    p = os.path.join(d, name)
    open(p, 'w', encoding='utf-8', newline='\n').write(raw[:ins_at] + ins_body + raw[ins_at:])
    return p


# V8 交互往返探针：派发一次真实点击，把渲染结果写进 DOM 再读回来。
# 现有判据问的都是「交互件在不在 / 脚脚本跑没跑」，没有一条问「点了有没有反应」——
# 于是这四类故障全都不会被拦：卡片索引错位（点第 2 张渲染第 1 张）、某个分支只在特定
# item 上抛错、事件绑定失效、面板只更新了一半。V3 的锚点证明的是初始化跑通了，不等于可用。
V8_PROBE = (
    '<script>/*V8PROBE*/'
    'window.addEventListener("load",function(){setTimeout(function(){'
    'var o=document.createElement("h1");o.id="v8probe";'
    'function done(t){o.textContent=t;document.body.appendChild(o)}'
    'try{'
    'var cards=document.querySelectorAll(".ix-card");'
    'var bodyEl=document.getElementById("ix-body");'
    'var titleEl=document.getElementById("ix-title");'
    'if(!cards.length){done("V8:NOCARD");return}'
    'var k=cards.length-1;'
    'var before=bodyEl?bodyEl.textContent:"";'
    'cards[k].click();'
    'setTimeout(function(){'
    'done("V8:"+k+"|"+(titleEl?titleEl.textContent:"")+"|"+(bodyEl?bodyEl.textContent:"")'
    '+ "|BEFORE:" + before)},250);'
    '}catch(e){done("V8:THROW:"+e.message)}'
    '},300)});</script>')


def _items_from_html(html):
    """取成品内联的数据集——作为「点了以后该渲染什么」的事实来源。"""
    lit = extract_var_literal(html, 'IX_ITEMS')
    if lit is None:
        return None
    try:
        items = json.loads(lit)
    except Exception:
        return None
    return items if isinstance(items, list) else None


def v8_checks(chrome, html_path, html, tmpdir):
    """V8 · 交互往返：派发点击 → 回读 DOM → 与内联数据源逐项比对。

    比对对象取数据源而不是第 0 项：「点了以后变了」证明不了「变对了」，
    卡片索引错位也是「变了」。所以要逐项对：初始渲染必须对第 0 项，点击第 k 张必须对第 k 项。
    """
    ok, skip, fail = [], [], []
    raw = open(html_path, encoding='utf-8').read()
    if 'id="ix-body"' not in markup_text(html):
        skip.append('V8 无可判对象：成品无交互件（gap 形态）')
        return ok, skip, fail
    items = _items_from_html(html)
    if not items or len(items) < 2:
        skip.append('V8 数据项不足（<2），点击既不点也看不出差别，本条不适用')
        return ok, skip, fail
    p = probe_copy(raw, V8_PROBE, '_v8_probe.html', tmpdir)
    if p is None:
        fail.append('V8 找不到探针插入位（成品既无 <head> 也无 </body>）')
        return ok, skip, fail
    dom = subprocess.run(
        [chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
         '--virtual-time-budget=6000', '--dump-dom', 'file:///' + p.replace('\\', '/')],
        capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
    m = re.search(r'id="v8probe">(V8:[^<]*)<', dom)
    if not m:
        fail.append('V8 探针未取到（页面可能在 load 之前就崩了，或被交互件脚本阻断）')
        return ok, skip, fail
    payload = m.group(1)[3:]
    if payload.startswith('THROW:'):
        fail.append('V8 派发点击时抛异常：%s' % payload[6:])
        return ok, skip, fail
    if payload == 'NOCARD':
        fail.append('V8 没有可点击的卡片（契约 C7：卡片须为 .ix-card 且带 data-ix 索引）')
        return ok, skip, fail
    k, got_title, got_body, before = payload.split('|', 3)
    k = int(k)
    before = before[len('BEFORE:'):]
    want0, wantk = items[0], items[k] if k < len(items) else None
    bad = []
    if before != str(want0.get('body') or ''):
        bad.append('初始渲染 %r ≠ 数据源第 0 项的 body %r' % (before[:24],
                                                       str(want0.get('body') or '')[:24]))
    if wantk is None:
        bad.append('点击的是第 %d 张卡，但数据源只有 %d 条' % (k, len(items)))
    else:
        if got_title != str(wantk.get('title') or ''):
            bad.append('点击第 %d 张卡后标题 %r ≠ 数据源第 %d 项 title %r'
                       % (k, got_title[:24], k, str(wantk.get('title') or '')[:24]))
        if got_body != str(wantk.get('body') or ''):
            bad.append('点击第 %d 张卡后正文 %r ≠ 数据源第 %d 项 body %r'
                       % (k, got_body[:24], k, str(wantk.get('body') or '')[:24]))
    if bad:
        fail.append('V8 交互往返不一致（点了没反应 / 索引错位 / 只更新一半）：%s'
                    % '；'.join(bad))
    else:
        ok.append('V8 交互往返一致：初始=第 0 项，点击第 %d 张卡渲染=第 %d 项（共 %d 张卡）'
                  % (k, k, k + 1))
    return ok, skip, fail


def _chrome_dump(chrome, path, budget=4000, window=''):
    """跑一次 headless dump-dom，失败/超时返回 None（不让异常变成裸回溯）。

    CI 与日常调用最常见的失败是「给了 chrome 参数但那个路径不可用」，那时不能抛回溯——
    调用方要的是一句「这批判据没跑」而不是 Python 栈。
    """
    try:
        cmd = [chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
               '--virtual-time-budget=%d' % budget]
        if window:
            cmd.append('--window-size=' + window)
        cmd += ['--dump-dom', 'file:///' + path.replace('\\', '/')]
        return subprocess.run(cmd, capture_output=True, timeout=120).stdout.decode(
            'utf-8', 'replace')
    except Exception:
        return None


def png_head_ok(path, want_w, want_h):
    """校验截图的 PNG 头与尺寸。返回 (是否合法, 说明)。只读 33 字节，不解码像素。

    单独成函数是为了可被单测——直接嵌在浏览器流程里，这条断言就永远无法被
    注入证明会失败（Chrome 正常时总产出合法 PNG），那就成了注释而不是闸门。
    """
    try:
        head = open(path, 'rb').read(33)
    except OSError as e:
        return False, '读取失败：%s' % e
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n':
        return False, '不是合法 PNG（前 8 字节不符或文件过短）'
    w = int.from_bytes(head[16:20], 'big')
    h = int.from_bytes(head[20:24], 'big')
    if (w, h) != (want_w, want_h):
        return False, '尺寸 %dx%d 与请求的 %dx%d 不符' % (w, h, want_w, want_h)
    return True, 'PNG 头合法，%dx%d' % (w, h)


def png_pixels_ok(path, min_colors=8, bands=4):
    """判断截图画面是不是一片空白。返回 (结论, 说明)，结论 ∈ 'ok' / 'blank' / 'unknown'。

    「文件存在 + 非空 + PNG 头合法 + 尺寸相符」对一张全白页**全部成立**——
    而 V7 声称守的是「截图可用」，空白截图的可用性是零，所以必须真的看像素。
    纯 stdlib（zlib + struct）解 PNG：逐行反滤波取真实像素，纵向均分 bands 段逐段
    采样数颜色，任一段颜色种数 < min_colors 即判空白。阈值依据（2026-09-20 实测，
    1080x2400、每 4 行/每 4 列采样）：三份真实成品每段 116–343 种颜色，
    纯色页 1–2 种，余量两个数量级。
    只支持 8bit 非隔行的灰度 / RGB / 灰度+alpha / RGBA（Chrome headless 实际产出
    8bit RGB）；别的形态返回 unknown——判不了就报出来，不冒充判过。
    """
    try:
        data = open(path, 'rb').read()
    except OSError as e:
        return 'unknown', '读取失败：%s' % e
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return 'unknown', '不是 PNG'
    ch_of = {0: 1, 2: 3, 4: 2, 6: 4}
    pos, idat, ihdr = 8, [], None
    while pos + 8 <= len(data):
        ln = int.from_bytes(data[pos:pos + 4], 'big')
        typ = data[pos + 4:pos + 8]
        if typ == b'IHDR' and ihdr is None:
            ihdr = data[pos + 8:pos + 8 + ln]
        elif typ == b'IDAT':
            idat.append(data[pos + 8:pos + 8 + ln])
        elif typ == b'IEND':
            break
        pos += 12 + ln
    if ihdr is None or len(ihdr) < 13 or not idat:
        return 'unknown', '缺 IHDR 或 IDAT，PNG 结构不完整'
    w = int.from_bytes(ihdr[0:4], 'big')
    h = int.from_bytes(ihdr[4:8], 'big')
    depth, ctype, inter = ihdr[8], ihdr[9], ihdr[12]
    if depth != 8 or ctype not in ch_of or inter != 0:
        return ('unknown', 'PNG 形态为 depth=%d ctype=%d interlace=%d，像素校验不适用'
                % (depth, ctype, inter))
    ch = ch_of[ctype]
    stride = w * ch
    try:
        raw = zlib.decompress(b''.join(idat))
    except zlib.error as e:
        return 'unknown', '像素数据解压失败：%s' % e
    if len(raw) < (stride + 1) * h:
        return 'unknown', '像素数据长度不足（%d < %d）' % (len(raw), (stride + 1) * h)
    step_y = max(1, h // 600)
    step_x = max(1, w // 300)
    seen = [set() for _ in range(bands)]
    prev = bytearray(stride)
    for y in range(h):
        off = y * (stride + 1)
        ft = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        if ft == 1:      # Sub：与左侧像素之差
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif ft == 2:    # Up：与上一行之差
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:    # Average：左右上三者均值
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:    # Paeth：线性预测取最近者
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if (pa <= pb and pa <= pc)
                                      else (b if pb <= pc else c))) & 0xFF
        elif ft != 0:
            return 'unknown', '未知的行滤波类型 %d' % ft
        prev = line
        if y % step_y == 0:
            s = seen[y * bands // h]
            for x in range(0, w, step_x):
                i = x * ch
                s.add(bytes(line[i:i + 3]) if ch >= 3 else bytes([line[i]]) * 3)
    flat = [i for i, s in enumerate(seen) if len(s) < min_colors]
    if flat:
        return ('blank', '纵向第 %s 段（共 %d 段）只采到 %d 种颜色（阈值 %d）——画面基本是纯色'
                % ('、'.join(str(i + 1) for i in flat), bands,
                   min(len(seen[i]) for i in flat), min_colors))
    return 'ok', '%d 段每段 ≥%d 种颜色' % (bands, min(len(s) for s in seen))


# V7 的动画冻结样式 + 终值钉住脚本（插在 <head> 之后，见 chrome_checks 内 V7 注释）。
# 钉终值时顺带摘掉 data-count/data-grow 属性：骨架的进场脚本拿的是求值期收集的元素表，
# 若只改文本不摘属性，load+150ms 起跳的计数动画会把钉好的终值再覆盖回去；摘掉属性后
# settle 走的是「加 .in」分支，计数彻底不启动。load 时先钉、2500ms 后再钉一次兜底。
# 实测时序依据（2026-09-20）：该环境下 rAF 与计时器都按极慢节拍推进（虚拟预算 4000
# 只够计数走 ~8%），但 load 之后注册的嵌套定时器一定触发。
V7_FREEZE = ('<style>/*V7FREEZE*/'
             '*{transition:none!important;animation:none!important}'
             'html.js .fx{opacity:1!important;transform:none!important}</style>'
             '<script>/*V7FREEZE*/'
             '(function(){function f(){'
             '[].slice.call(document.querySelectorAll("[data-count]")).forEach('
             'function(el){var v=el.getAttribute("data-count");if(v===null){return}'
             'el.removeAttribute("data-count");el.textContent=v});'
             '[].slice.call(document.querySelectorAll("[data-grow]")).forEach('
             'function(el){var v=el.getAttribute("data-grow");if(v===null){return}'
             'el.removeAttribute("data-grow");el.style.width=v});}'
             'window.addEventListener("load",function(){f();'
             'window.setTimeout(f,2500)})})();</script>')


def chrome_checks(html_path, chrome, js_value, shot):
    """B5 / V3 / V5 / V7 / V8。

    缺 --js-value / --shot 时，对应判据列 SKIP，不静默消失（SKIP 不计入通过）。
    缺 --chrome 或路径不存在时整组列 SKIP——**这也是本仓最容易出假绿的一处**：
    CI 里 `$(command -v google-chrome)` 返回空串时，这组判据同样一行不出，
    退出码还是 0。所以调用方必须配 `--expect` 断言本该出现的条数。
    """
    ok, skip, fail = [], [], []
    if not chrome or not os.path.exists(chrome):
        # 判据号必须写在行首：U1 出席检查、以及 negative_test 的期望命中都靠行首的那个号。
        # 旧写法是「浏览器判据（B5/V3/V5/V7/V8）跳过」，中文在前——于是这五条在出席检查里
        # 被判成「压根没出现」，而它们明明是列了 SKIP 的。
        return ([], ['B5/V3/V5/V7/V8 未执行：--chrome 未给或路径不存在，浏览器判据本次整体'
                     '跳过（不计入通过）'], [])
    # 交给 Chrome 的路径一律绝对化——**只在这一处做**，别回各调用点再补一次。
    # 依据（2026-09-20 本机 Windows 实测）：Chrome 不认相对路径的 --screenshot，
    # 报 `Failed to write file …: 拒绝访问`；同一命令换绝对路径即正常写入（395 KB）。
    # file:/// 同理是 URL 语义、不按 CWD 解析——这条平时走不到（probe_copy 成功时用的
    # 已是 tmpdir 绝对路径），只有注入失败、回落到 html_path 那个分支才会露出来。
    # Linux / macOS 上恰好能过（Chrome 按 CWD 解析相对路径），所以这是只在 Windows 炸的坑；
    # 而「只在某个平台炸」的前提是「那个平台也真的在跑这批判据」——见 ci.yml 的覆盖注释。
    html_path = os.path.abspath(html_path) if html_path else html_path
    shot = os.path.abspath(shot) if shot else shot
    raw = read_text(html_path)
    html = raw
    # 探针副本落在一次性唯一目录：并发两跑 / 中断残留不再互相覆盖
    tmpdir = tempfile.mkdtemp(prefix='pd_probe_')
    try:
        # ---- B5：浏览器无 console 错误与未捕获异常 ----
        b5p = probe_copy(raw, B5_PROBE, '_b5_probe.html', tmpdir)
        if b5p is None:
            fail.append('B5 成品缺少插入位，无法注入错误捕获探针')
            return ok, skip, fail
        dom = _chrome_dump(chrome, b5p, 4000)
        if dom is None:
            fail.append('B5 浏览器启动失败或超时')
            return ok, skip, fail
        pf = re.search(r'id="b5probe">([^<]*)<', dom)
        if not dom or not pf:
            fail.append('B5 探针未取到（页面可能在 load 之前就崩了）')
            return ok, skip, fail
        payload = pf.group(1)
        mm = re.match(r'ERRN:(\d+)\|', payload)
        if mm:
            payload = payload[mm.end():]
        rows = [x.strip() for x in payload.split(';;') if x.strip()]
        hard = [x for x in rows if x.startswith(('CE:', 'ERR:', 'REJ:'))]
        soft = [x for x in rows if x.startswith('CW:')]
        if hard:
            fail.append('B5 浏览器报错 %d 条：%s' % (len(hard), '；'.join(hard[:4])))
        else:
            ok.append('B5 无 console 错误与未捕获异常（dump-dom %d 字符%s）'
                      % (len(dom), '，另有 %d 条 warn' % len(soft) if soft else ''))
        # V3：注入值只在 DOM 里、不在原始源码里 → 证明 JS 真执行了
        if js_value:
            if js_value in raw:
                fail.append('V3 注入值在原始源码中已存在，无法证明 JS 执行')
            elif js_value in dom:
                ok.append('V3 JS 已执行：注入值 "%s" 出现在 DOM' % js_value)
            else:
                fail.append('V3 JS 未执行：注入值 "%s" 未出现在 DOM' % js_value)
        else:
            skip.append('V3 未执行：未给 --js-value，JS 执行探针无值可验（不计入通过）')
        # V5：副本挂测量脚本读 scrollWidth/clientWidth（副本不改布局）
        mp = os.path.join(tmpdir, '_measure_probe.html')
        probe = ('<script>window.addEventListener("load",function(){'
                 'var d=document.documentElement,t=document.createElement("h1");'
                 't.id="probe";t.textContent="OW:"+(d.scrollWidth-d.clientWidth);'
                 'document.body.appendChild(t)});</script>')
        open(mp, 'w', encoding='utf-8', newline='\n').write(
            raw.replace('</body>', probe + '</body>'))
        dom2 = _chrome_dump(chrome, mp, 4000, window='1080,900') or ''
        m = re.search(r'id="probe">OW:(-?\d+)<', dom2)
        if not m:
            fail.append('V5 溢出测量未取到探针值')
        elif int(m.group(1)) > 0:
            fail.append('V5 存在横向溢出 %s px' % m.group(1))
        else:
            ok.append('V5 无横向溢出（scrollWidth-clientWidth=0）')
        # V8：交互往返——唯一一条问「点了有没有反应」的判据
        o, s, f = v8_checks(chrome, html_path, html, tmpdir)
        ok += o
        skip += s
        fail += f
        # V7 截图——用「动画冻结」副本，不用原件：
        # 判的是内容在场与画面非空白，不是动画时序。实测（2026-09-20，v1.5 带进场动画的成品）：
        # 同一文件 budget 4000/12000/15000/20000 四次截图的显形状态互相矛盾，其中 4000 与
        # 20000 两张字节级相同——转场在截图模式下按帧推进，是竞态不是时长问题，调预算救不了。
        # 冻结后内容必然呈终态；对空白故障的拦截不受影响（visibility 类注入照样把画面藏空，
        # negative_test 的空白注入仍必须被拦）。附带收益：.fx 若没有 .js 门控（v1.4.1 的
        # A 缺陷形态），冻结 CSS 只放行带门控的隐藏，无门控的 .fx 依旧隐藏——V7 从此也拦它。
        if shot:
            p7 = probe_copy(raw, V7_FREEZE, '_v7_probe.html', tmpdir) or html_path
            subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
                            '--window-size=1080,2400', '--virtual-time-budget=4000',
                            '--screenshot=' + shot,
                            'file:///' + p7.replace('\\', '/')],
                           capture_output=True, timeout=120)
            if not os.path.exists(shot) or os.path.getsize(shot) == 0:
                fail.append('V7 截图未生成或为空')
            else:
                # 三层递进：「非空」拦不住写坏的图 → 头与尺寸拦不住一张全白页
                # （那三样对空白页全部成立）→ 所以最后还得真的看像素。
                good, why = png_head_ok(shot, 1080, 2400)
                if not good:
                    fail.append('V7 截图有问题：%s' % why)
                else:
                    verdict, why2 = png_pixels_ok(shot)
                    if verdict == 'ok':
                        ok.append('V7 截图完整且画面非空白（%s；%s，%d 字节）'
                                  % (why, why2, os.path.getsize(shot)))
                    elif verdict == 'blank':
                        fail.append('V7 截图画面空白：%s' % why2)
                    else:
                        fail.append('V7 截图像素无法校验：%s' % why2)
        else:
            skip.append('V7 未执行：未给 --shot，本次未请求截图（不计入通过）')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return ok, skip, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html', nargs='?', help='成品 HTML（--self-test 模式下可省）')
    ap.add_argument('--profile', help='profiles/<产品>/profile.json（N5 分档与 V4 数据源取自这里）')
    ap.add_argument('--data')
    ap.add_argument('--img', type=int, default=None)
    ap.add_argument('--js-value')
    ap.add_argument('--chrome')
    ap.add_argument('--shot')
    ap.add_argument('--r1', help='元判据 R1 的词表（缺省取 profile 的 product/vendor）')
    ap.add_argument('--json')
    ap.add_argument('--expect', help='期望契约 pass=n,fail=n,skip=n —— 把文档里的数字变成机器判据')
    ap.add_argument('--deliver', help='已落盘的那份成品路径；给出则追加跑 D1–D5 落盘闸门')
    ap.add_argument('--self-test', action='store_true',
                    help='跑单测：证明那些注入动不了的断言会失败（含 V7）')
    a = ap.parse_args()

    if a.self_test:
        sys.exit(self_test())
    if not a.html:
        ap.error('缺少成品 HTML 路径（--self-test 模式除外）')

    raw_bytes = open(a.html, 'rb').read()
    ok, skip, fail = [], [], []
    # 出席登记：有些判据**按设计**不占 PASS/FAIL/SKIP 行（U2 成立时不占行，否则每加一条
    # 元判据，--expect 里的数字就得 +1，那个数字就不再表示「被判的条目数」）。
    # 出席的意义是「这条判据本次真的执行并给了结论」，不是「它产出了一行」，
    # 所以另设一个登记处——只查行会把守规矩的判据自己判成缺席。
    reported = set()

    # 配置
    prof, pdir = None, ''
    if a.profile:
        pdir = os.path.dirname(os.path.abspath(a.profile))
        try:
            prof = json.loads(read_text(a.profile))
            ok.append('配置读取通过：%s' % os.path.basename(a.profile))
        except Exception as e:
            fail.append('配置读取失败 --profile %s：%s' % (a.profile, e))

    data_path = a.data
    if not data_path and prof:
        rel = ((prof.get('interaction') or {}).get('data')) or ''
        if rel:
            p = rel if os.path.isabs(rel) else os.path.join(pdir, rel)
            if os.path.isfile(p):
                data_path = p

    content_path = None
    if prof:
        rel = prof.get('content') or ''
        if rel:
            p = rel if os.path.isabs(rel) else os.path.join(pdir, rel)
            if os.path.isfile(p):
                content_path = p

    # B4 编码
    if raw_bytes[:3] == b'\xef\xbb\xbf':
        fail.append('B4 存在 UTF-8 BOM')
    try:
        html = raw_bytes.decode('utf-8')
        ok.append('B4 UTF-8 解码通过')
    except Exception as e:
        fail.append('B4 非 UTF-8：%s' % e)
        html = raw_bytes.decode('utf-8', 'replace')
    if re.search(r'<meta\s+charset=["\']?utf-8', html, re.I):
        ok.append('B4 含 meta charset')
    else:
        fail.append('B4 缺少 <meta charset="utf-8">')

    # B1 / V1 外部引用：属性 + CSS 层的 url()/@import/srcset 全部纳入
    # 只扫 src/href 属性会漏掉三种联网写法：@import url("//…")、background:url(//…)、
    # srcset="https://… 2x"。这三种都能让「离线自包含」这条硬判据在 CSS 层完全敞开。
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    ext = external_refs(html)
    if ext:
        fail.append('B1/V1 存在 %d 处外部引用：%s' % (len(ext), ', '.join(ext[:3])))
    else:
        ok.append('B1/V1 外部引用 0（属性 %d 处，含 CSS url()/@import/srcset）' % len(refs))

    # B3 体积
    if len(raw_bytes) <= 3 * MB:
        ok.append('B3 体积 %.2f MB ≤ 3 MB' % (len(raw_bytes) / MB))
    else:
        fail.append('B3 体积 %.2f MB > 3 MB' % (len(raw_bytes) / MB))

    # B6 绝对路径（先剥 URL，否则 https:// 里的 "s:/" 会被当成盘符路径）
    hits = [h for h in (x.strip() for x in ABS_PATH.findall(strip_urls(html))) if h][:3]
    if hits:
        fail.append('B6 出现本机绝对路径：%s' % ', '.join(hits))
    else:
        ok.append('B6 无本机绝对路径（先剥 URL 再匹配）')

    # B7 占位符
    ph = PLACEHOLDER.findall(html)
    if ph:
        fail.append('B7 占位符残留：%s' % ', '.join(sorted(set(ph))[:5]))
    else:
        ok.append('B7 占位符残留 0')

    # B8 脚本/样式标签配对且不嵌套
    # 嵌套 <script> 会让整个脚本块静默不执行，而源码看上去完全正常。
    # 这条不依赖浏览器，就是为了让「本来只有在浏览器里才看得出来」的故障提前暴露。
    b8, covered = [], []
    for tag, cn in (('script', '脚本'), ('style', '样式')):
        o = len(re.findall(r'<%s\b[^>]*>' % tag, html))
        c = len(re.findall(r'</%s\s*>' % tag, html))
        covered.append('%s×%d' % (tag, o))
        if o != c:
            b8.append('B8 <%s> 标签不配对（开 %d / 闭 %d）' % (tag, o, c))
            continue
        n = len([m for m in re.finditer(r'(?s)<%s\b[^>]*>(.*?)</%s\s*>' % (tag, tag), html)
                 if re.search(r'</?%s\b' % tag, m.group(1))])
        if n:
            b8.append('B8 出现嵌套 <%s>（%d 处）：浏览器在第一个 </%s> 处截断，%s块静默失效'
                      % (tag, n, tag, cn))
    if b8:
        fail += b8
    else:
        ok.append('B8 脚本/样式标签配对且不嵌套（%s）' % '、'.join(covered))

    o, s, f = img_checks(html, a.img)
    ok += o
    skip += s
    fail += f

    o, s, f = value_checks(html, data_path)
    ok += o
    skip += s
    fail += f

    o, s, f = stats_checks(html, content_path)
    ok += o
    skip += s
    fail += f

    o, s, f = narrative_checks(html, prof)
    ok += o
    skip += s
    fail += f

    o, s, f = interaction_checks(html, prof)
    ok += o
    skip += s
    fail += f

    o, s, f = chrome_checks(a.html, a.chrome, a.js_value, a.shot)
    ok += o
    skip += s
    fail += f

    # R1 元判据：判据族脚本自身零产品相关分支。
    # 编号从 1 起——此前叫 R2 却没有 R1，读者会以为漏了一条；而一旦去掉编号，
    # 「FAIL [A-Z]\d」这个判据号格式就失效，negative_test 再也引用不到它。
    r1 = a.r1
    if not r1 and prof:
        r1 = ','.join(w for w in (prof.get('product'), prof.get('vendor')) if w)
    if r1:
        here = os.path.dirname(os.path.abspath(__file__))
        words = [w.strip() for w in r1.split(',') if w.strip()]
        # 判据族：正向核验器 + 负向测试。两者任一带产品分支，都会给某产品开后门
        fam, bad = ('check_demo.py', 'negative_test.py'), []
        for fn in fam:
            p = os.path.join(here, fn)
            if not os.path.isfile(p):
                continue
            txt = read_text(p)
            for w in words:
                # 词条匹配与 audit_body 共用一份实现（measure_density.word_hit）：
                # 两处各写一遍已经发生过——右边一个加了词边界、另一个没有。
                if word_hit(txt, w):
                    bad.append('%s 命中 %s' % (fn, w))
        if bad:
            fail.append('R1 判据族脚本出现产品词：%s' % '；'.join(bad))
        else:
            ok.append('R1 判据族（%d 个脚本）零产品相关分支（%d 个词全不命中）'
                      % (len(fam), len(words)))
    else:
        # 词表为空时这条判据恒不命中。旧版在这里整段消失——既不 PASS 也不 SKIP，
        # 于是「没查」被读成「查过且干净」。显式报 SKIP，与文件头声明的三态一致。
        skip.append('R1 判据族自身零产品分支：未给 --r1 且 profile 未声明 product/vendor，'
                    '词表为空，本次未执行（不计入通过）')

    # ---- U1 出席检查：登记过的判据必须逐条出结论 ----
    # 历史上三次「静默消失」都是同一类：V3/V7 缺参数时整段不出（v1.3.0 修）、
    # V2 在成品无图时一行不出（本轮修）。逐条补 \\ 是打地鼠——改成对着登记表查出席，
    # 以后任何判据在任何分支上忘了出结论，都会被这一条抓住。
    # 实际的出席判定已移到 D1–D5 之后：D 系列的结论行要参与出席判定，
    # 而这一族是在落盘阶段才产生的。放在这里会当场把 D1–D5 全判成缺席。

    # ---- U2 期望契约：把文档里的数字变成机器契约 ----
    expect_ok = ''
    if a.expect:
        want = {}
        for kv in a.expect.replace('；', ',').replace(' ', ',').split(','):
            if not kv.strip():
                continue
            if '=' not in kv:
                fail.append('U2 --expect 写法不合法（应为 pass=n,fail=n,skip=n）：%r' % kv)
                continue
            k, v = kv.split('=', 1)
            k = k.strip().lower()
            if k not in ('pass', 'fail', 'skip'):
                fail.append('U2 --expect 只认 pass/fail/skip 三个键，收到 %r' % k)
                continue
            try:
                want[k] = int(v)
            except ValueError:
                fail.append('U2 --expect 的值必须是整数：%r' % kv)
        got = {'pass': len(ok), 'fail': len(fail), 'skip': len(skip)}
        off = ['%s 期望 %d，实测 %d' % (k, want[k], got[k]) for k in want if want[k] != got[k]]
        if off:
            fail.append('U2 期望契约不符：%s —— 文档里的数字漂了而没有改文档，等于契约失效'
                        % '；'.join(off))
        else:
            # 成立时不占一行 PASS：否则每加一条元判据，文档里的期望数字就得跟着 +1，
            # 「23」这种数字就不再表示「被判的条目数」了。结论打到汇总行下面，照样可 grep。
            expect_ok = '、'.join('%s %d' % (k, want[k]) for k in sorted(want))
            reported.add('U2')

    # ---- D1–D5 落盘闸门：只对「已经复制到落点之后的那份」判 ----
    # 必须排在 U1 出席检查之前——否则 D 系列的结论行还没产生就被判成缺席。
    if a.deliver:
        o, s, f = delivery_checks(a.html, a.deliver, upstream_fail=len(fail))
        ok += o
        skip += s
        fail += f

    # ---- U1 出席检查：登记过的判据必须逐条出结论 ----
    # 历史上三次「静默消失」都是同一类：V3/V7 缺参数时整段不出（v1.3.0 修）、
    # V2 在成品无图时一行不出（本轮修）、D2/D3/D5 在落点不存在时整段不出（本轮修）。
    # 逐条补是打地鼠——改成对着登记表查出席，以后任何判据在任何分支上忘了出结论，
    # 都会被这一条抓住。
    seen = set()
    for line in ok + skip + fail:
        m = re.match(r'([A-Z]\d(?:/[A-Z]\d)*)\b', line)
        if m:
            seen |= set(m.group(1).split('/'))
    # U1 自己也要出席，但它通过时故意不占 PASS 行——否则每加一条元判据，--expect 里
    # 的数字就得跟着 +1，「23」就不再表示「被判的条目数」了。执行到这里本身就是出席证据。
    reported.add('U1')
    # 条件性出席：某一族本次根本没跑到时，要求它出结论只会把原本 PASS 的路径判红。
    # 所以「要求出席」与「本次是否跑到了这一族」必须同源，不能一边扩面一边漏补分支。
    required = list(CRITERIA_ARGS) + ['U1']
    if a.expect:
        required.append('U2')
    if a.deliver:
        required += ['D1', 'D2', 'D3', 'D4', 'D5']
    for cid in required:
        if cid not in seen and cid not in reported:
            fail.append('U1 判据 %s 本次既没有结论行、也没有登记出席——'
                        '「没查」不许被读成「查过且干净」' % cid)

    for line in ok:
        print('PASS  ' + line)
    for line in skip:
        print('SKIP  ' + line)
    for line in fail:
        print('FAIL  ' + line)
    print('\n判定：%s（PASS %d / FAIL %d / SKIP %d）'
          % ('PASS' if not fail else 'FAIL', len(ok), len(fail), len(skip)))
    if skip:
        print('      跳过不等于通过——下列判据本次未执行：')
        for line in skip:
            print('        · ' + line)
    if expect_ok:
        print('      期望契约成立（%s）—— 这里的每一条都由 --expect 机器断言，'
              '不再只是文档里的数字' % expect_ok)
    if a.json:
        json.dump({'html': a.html, 'pass': ok, 'skip': skip, 'fail': fail},
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    sys.exit(1 if fail else 0)


# ---------------------------------------------------------------- D1–D5 落盘闸门
# 版本号段用 `\d+(?:\.\d+)*`：只写 `\d+\.\d+` 时，`_v1.6.0_2026-09-20` 这种三位版本号
# 会被判成「不含版本与日期」——判的是命名约定，不是段数约定，段数不该卡死。
D1_NAME = re.compile(r'_v\d+(?:\.\d+)*_\d{4}-\d{2}-\d{2}$')


def sha256_of(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(65536), b''):
            h.update(blk)
    return h.hexdigest()


def _git(args, cwd):
    try:
        return subprocess.run(['git'] + args, cwd=cwd, capture_output=True,
                              timeout=60).stdout.decode('utf-8', 'replace')
    except Exception:
        return None


def delivery_checks(src, dst, upstream_fail=0):
    """D1–D5：交付链最后一公里。此前这一组只写在 SKILL.md 正文里，靠人记，也无人复核。

    D1（上游闸门已通过）以前只在注释里说「由调用方保证」——那就是没有判据。现在调用方
    把自己已判出的 FAIL 数传进来，0 才 PASS；上游还红着就落盘，等于把没过的件发出去。
    D2 兜底存在 / D3 文件名带版本与日期 / D4 回读非空且与源 sha256 一致 / D5 提交信息编码可读。
    """
    ok, skip, fail = [], [], []

    # D1 上游闸门：由调用方把「落到这一步之前已经判出多少 FAIL」传进来
    if upstream_fail == 0:
        ok.append('D1 上游闸门本次无 FAIL（判据族全过才允许谈落盘）')
    else:
        fail.append('D1 上游闸门尚有 %d 条 FAIL —— 落盘判据建立在「上游已过」之上，'
                    '上游没过就没有可交付的东西' % upstream_fail)

    if not os.path.isfile(dst):
        fail.append('D4 落盘成品不存在：%s —— 先把成品复制到落点，再回来验' % dst)
        # 落点不存在时其余三条判不了。以前这里直接 return，于是「没查」被读成「查过了」；
        # 现在逐条报 SKIP，和 U1 的出席口径一致。
        for cid, why in (('D2', '落点不存在，兜底无从判起'),
                         ('D3', '落点不存在，文件名无从判起'),
                         ('D5', '落点不存在，提交信息无从判起')):
            skip.append('%s 本次未验证：%s' % (cid, why))
        return ok, skip, fail
    d = os.path.dirname(os.path.abspath(dst)) or '.'
    base = os.path.basename(dst)
    stem = base.rsplit('.', 1)[0]

    # D3 文件名匹配 _v<版本>_<日期>
    if D1_NAME.search(stem):
        ok.append('D3 文件名含版本与日期：%s' % base)
    else:
        fail.append('D3 文件名 %s 不含 `_v<版本>_<日期>` —— 收件人分不出这是哪一版' % base)

    # D4 回读 size > 0 且 sha256 与源一致
    if os.path.getsize(dst) == 0:
        fail.append('D4 落盘成品为空文件：%s' % dst)
    else:
        a, b = sha256_of(src), sha256_of(dst)
        if a == b:
            ok.append('D4 落盘与源件逐字节一致（sha256 %s…）' % a[:12])
        else:
            fail.append('D4 落盘成品与源件不一致（源 %s… / 落盘 %s…）' % (a[:12], b[:12]))

    # D2 兜底存在（git 仓内 → 已 commit 且工作树干净；非 git → 同 sha256 副本）
    inside = _git(['rev-parse', '--is-inside-work-tree'], d)
    if inside and inside.strip() == 'true':
        dirty = _git(['status', '--porcelain'], d)
        if dirty is None:
            skip.append('D2 git 兜底无法判定：git 调用失败，本次未验证')
        elif dirty.strip():
            fail.append('D2 git 工作树不干净（%d 处未提交）—— 没有 commit 就没有兜底'
                        % len([x for x in dirty.strip().splitlines() if x.strip()]))
        else:
            ok.append('D2 git 兜底存在：工作树干净且已入库')
        # D5：提交信息编码可读——`-m` 在 Windows 上会把中文写花，所以约定用 -F 传 UTF-8 文件
        msg = _git(['log', '-1', '--format=%B'], d)
        if msg is None or not msg.strip():
            skip.append('D5 提交信息取不到，本次未验证')
        elif '�' in msg:
            fail.append('D5 最近一条提交信息已乱码（应当用 `git commit -F <UTF-8 文件>`）')
        else:
            ok.append('D5 最近一条提交信息编码可读')
    else:
        here = sha256_of(dst)
        twins = [f for f in glob.glob(os.path.join(d, '*'))
                 if os.path.isfile(f) and os.path.abspath(f) != os.path.abspath(dst)
                 and sha256_of(f) == here]
        if twins:
            ok.append('D2 非 git 兜底：存在同 sha256 副本 %s' % os.path.basename(twins[0]))
        else:
            fail.append('D2 没有兜底：既不在 git 仓内，也没有同 sha256 的副本')
        # D5 提交信息只在 git 仓里才有意义；非 git 落点此前整条不出现（静默消失），
        # 现显式报 SKIP——出席的意义是「没查」不许被读成「查过且干净」。
        skip.append('D5 本次未验证：落点不在 git 仓内，无从判提交信息编码')
    return ok, skip, fail


# ---------------------------------------------------------------- 单测模式
def _png_bytes(w, h, mode='flat'):
    """造一张合法的最小 PNG（真彩 8bit RGB），供 V7 的单测用。

    mode='flat'   全零像素——一整片纯色（空白页的形态）
    mode='half'   上半随坐标变化、下半纯色——「只有上半有内容」的形态
    mode='varied' 全图随坐标变化——正常渲染出的页面
    """
    import zlib

    def chunk(typ, data):
        return (struct.pack('>I', len(data)) + typ + data
                + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff))
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # 行滤波类型 0（None），本行字节即像素原值
        for x in range(w):
            if mode == 'flat' or (mode == 'half' and y >= h // 2):
                rows += b'\x00\x00\x00'
            else:
                rows += bytes(((x * 7) % 256, (y * 11) % 256, (x + y) % 256))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows)))
            + chunk(b'IEND', b''))


def self_test():
    """证明那些「注入动不了」的断言确实会失败。

    V7 的像素校验：往 HTML 里注什么都没有用，只能从函数层证伪——
    纯色页 / 只有上半有内容的页必须判空白，正常页必须放行。
    同一类还有剥注释、外链提取、URL 剥离：它们是纯函数，写成单测最省事也最可靠。
    """
    tmp = tempfile.mkdtemp(prefix='pd_selftest_')
    rows = []
    try:
        # ---- V7：png_head_ok ----
        good = os.path.join(tmp, 'good.png')
        open(good, 'wb').write(_png_bytes(1080, 2400))
        rows.append(('V7', '合法 PNG 且尺寸相符', True, png_head_ok(good, 1080, 2400)[0]))
        wrong = os.path.join(tmp, 'wrong.png')
        open(wrong, 'wb').write(_png_bytes(640, 480))
        rows.append(('V7', '尺寸不符必须判坏', False, png_head_ok(wrong, 1080, 2400)[0]))
        trunc = os.path.join(tmp, 'trunc.png')
        open(trunc, 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 4)
        rows.append(('V7', 'PNG 头被截断必须判坏', False, png_head_ok(trunc, 1080, 2400)[0]))
        empty = os.path.join(tmp, 'empty.png')
        open(empty, 'wb').write(b'')
        rows.append(('V7', '空文件必须判坏', False, png_head_ok(empty, 1, 1)[0]))
        rows.append(('V7', '文件不存在必须判坏', False,
                     png_head_ok(os.path.join(tmp, 'nope.png'), 1, 1)[0]))
        # ---- V7：png_pixels_ok（像素校验——头与尺寸都对也拦不住的空白页）----
        blank = os.path.join(tmp, 'blank.png')
        open(blank, 'wb').write(_png_bytes(100, 400))
        rows.append(('V7', '整页纯色必须判空白', 'blank', png_pixels_ok(blank)[0]))
        half = os.path.join(tmp, 'half.png')
        open(half, 'wb').write(_png_bytes(100, 400, 'half'))
        rows.append(('V7', '只有上半有内容也必须判空白', 'blank', png_pixels_ok(half)[0]))
        full = os.path.join(tmp, 'full.png')
        open(full, 'wb').write(_png_bytes(100, 400, 'varied'))
        rows.append(('V7', '全图内容丰富必须放行', 'ok', png_pixels_ok(full)[0]))
        # ---- I2：剥注释 ----
        rows.append(('I2', '块注释里的调用会被剥掉', True,
                     'IX_init()' not in strip_js_comments('/*\nIX_init();\n*/')))
        rows.append(('I2', '行注释里的调用会被剥掉', True,
                     'IX_init()' not in strip_js_comments('// IX_init();\nIX_render(0);')))
        rows.append(('I2', '真调用不会被误剥', True,
                     strip_js_comments('\nIX_init();').count('IX_init()') == 1))
        rows.append(('I2', 'URL 里的 // 不被当注释', True,
                     'https://x.cn/a' in strip_js_comments('var u="https://x.cn/a";')))
        # ---- B1/V1：外链提取 ----
        rows.append(('B1', 'CSS @import 与 url() 外链必须被抓到', True,
                     {'//evil.example.com/a.css', '//evil.example.com/b.png'}
                     <= set(external_refs(
                         '<style>@import url("//evil.example.com/a.css");'
                         'body{background:url(//evil.example.com/b.png)}</style>'))))
        rows.append(('B1', 'srcset 外链必须被抓到', True,
                     'https://evil.example.com/x.png' in external_refs(
                         '<img src="data:image/png;base64,AA" '
                         'srcset="https://evil.example.com/x.png 2x">')))
        rows.append(('B1', 'data: 与页内锚点不算外链', True,
                     external_refs('<img src="data:image/png;base64,AA">'
                                   '<a href="#top">x</a>') == []))
        # ---- B6：先剥 URL 再判路径 ----
        rows.append(('B6', '普通网址不再误判成本机路径', True,
                     not ABS_PATH.search(strip_urls('参考资料：https://example.com/doc'))))
        rows.append(('B6', 'Windows 盘符路径仍要命中', True,
                     bool(ABS_PATH.search(strip_urls('C:\\Users\\someone\\a.png')))))
        rows.append(('B6', 'UNC 路径要命中', True,
                     bool(ABS_PATH.search(strip_urls('\\\\srv\\share\\a.png')))))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [(cid, name) for cid, name, want, got in rows if want != got]
    print('单测（证明那些注入动不了的断言确实会失败）：')
    for cid, name, want, got in rows:
        print('  %-4s %-30s 期望 %-5s 实测 %-5s %s'
              % (cid, name, want, got, 'OK' if want == got else 'FAIL'))
    print('  覆盖判据：%s' % '、'.join(sorted(set(cid for cid, _n, _w, _g in rows))))
    print('单测结论：%s' % ('PASS（%d 条用例全部符合预期）' % len(rows) if not bad
                        else 'FAIL（%d 条用例没按预期失败：%s）'
                        % (len(bad), '；'.join('%s %s' % (c, n) for c, n in bad))))
    return 0 if not bad else 1


if __name__ == '__main__':
    main()
