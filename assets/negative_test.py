#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V6 负向测试：逐条注入故障，确认核验器真的会 FAIL。

用法：
  python negative_test.py <html> [--profile <profile.json>] [--data <数据源.json>]
                          [--img N] [--js-value S] [--chrome <chrome.exe>]
                          [--workdir <临时目录>] [--json <report.json>]

原理：能被证明会失败的检查器才是检查器。任一条故障注入后核验器仍 PASS，
说明该判据是假绿——本脚本自身退出码 1。

三条纪律：
  1. 判据族共用同一份实现——文本口径、词条匹配、字面量提取、判据登记表都从 check_demo /
     measure_density 取，避免「核验器」与「证明核验器有效」两处各写一遍然后漂移。
  2. 中间产物默认落在成品同级目录 `_negtest/`，跑完自清；不放 %TEMP%。
  3. **覆盖率是机器判的，不是靠自觉**：凡本次调用参数下跑得到的判据，若没有注入用例，
     末行 CY（覆盖率）直接 FAIL——“每条判据必须能被证明会失败”这条规矩此前只写在
     CONTRIBUTING.md 里，于是 B5 与 V7 两条判据长期没有任何注入而无人发现。
     （V7 曾被豁免去走单测——那是它只验头与尺寸的年代；补上像素校验后，一条把可见
     内容整体藏掉的 CSS 注入就能让截图变纯色，HTML 注入动得了它了，于是拉回注入路径。
     给 --chrome 时本脚本自动备好 --shot，V7 每轮都真跑。）
     纯函数层的证明仍在：`check_demo.py --self-test` 会真的去跑，不是嘴上说有。

三态语义（缺条件既不许冒充通过，也不许冒充失败）：
  PASS = 注入后核验器确实 FAIL，且命中了期望的判据号；
  SKIP = 该注入在本次成品形态下不适用（成品无内联图 / 需 --chrome 未给 /
         需 --profile 未给），单独计数，不计入通过；
  FAIL = 注入后核验器仍 PASS（假绿），或注入未生效却契约要求该特征（成品缺陷）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_demo import CRITERIA_ARGS, UNIT_PROVEN, extract_var_literal  # noqa: E402

CHECK = os.path.join(HERE, 'check_demo.py')
# 判据 → 跑它需要哪些调用参数。单一事实来源在 check_demo.CRITERIA_ARGS；
# 早先这里另抄了一份 NEEDS_ARG，两份迟早不同步（这是本仓已经发生过一次的毛病）。
ARG_HINT = {'chrome': '--chrome', 'shot': '--shot', 'js_value': '--js-value'}

# (故障名, 期望被触发的判据, 注入函数, profile 补丁, 依赖的成品特征)
FAULTS = []


def fault(name, expect, patch=None, needs=None, extra=None):
    """needs：该注入依赖的成品特征。

    取 'img' 时表示注入点是一张内联图——成品若本来就没有图（例如交互件走
    无图形态），这里注入不进去属于「测量条件不成立」，不是成品缺陷。默认
    None＝无条件可注入。见 main() 里对注入未生效的分流。

    extra：给核验器追加的参数（如 R1 那条要靠 `--r1` 换词表）——故障不一定只能改 HTML，
    也可以落在**调用参数**上。早先只有改 HTML 一条路，于是「判据族脚本里出现产品词」
    这条元判据永远无处可注。
    """
    def deco(fn):
        FAULTS.append((name, expect, fn, patch, needs, extra))
        return fn
    return deco


def unverifiable_ids(want, a):
    """本次调用参数下，expect 里哪些判据根本跑不到。返回 [(判据, 缺的参数)]。"""
    out = []
    for w in sorted(want):
        missing = _missing_arg(w, a)
        if missing:
            out.append((w, missing))
    return out


def _missing_arg(w, a):
    """判据 w 在本轮参数下缺什么（返回提示串；不缺返回 ''）。"""
    for k in CRITERIA_ARGS.get(w, ()):
        val = getattr(a, k, None)
        if not val or (k == 'chrome' and not os.path.exists(val)):
            return ARG_HINT[k]
    return ''


def judge(returncode, want, failed_ids, unver):
    """判定一条注入的结果 → (结论, 说明)。

    多值期望是**并发**要求：expect 里每一条都要命中才算通过。旧版用交集判定，
    `I2,V3` 只要 I2 命中就印 PASS——V3 从未被验证，报告上看不出来。
    「本次跑不到」的期望不算失败，但必须在结论里点名，不许静默消失。
    """
    hit = want & failed_ids
    unver_ids = set(w for w, _ in unver)
    miss = (want - failed_ids) - unver_ids
    note = '；'.join('%s 未验证：%s' % (w, r) for w, r in unver)
    if returncode != 0 and hit and not miss:
        return 'PASS', '核验器 FAIL（命中 %s%s）' % (
            ','.join(sorted(hit)), '；' + note if note else '')
    if returncode != 0 and hit:
        return 'FAIL', ('只命中 %s，期望 %s 没被触发——该判据没拦住这个注入'
                        % (','.join(sorted(hit)), ','.join(sorted(miss))))
    if returncode != 0:
        return 'WARN', '核验器 FAIL 但命中其他：%s' % ','.join(sorted(failed_ids))
    return 'FAIL', '核验器仍 PASS —— 该判据是假绿'


def _dumps(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':'))


def _swap_items(h, fn):
    """取出内联的 IX_ITEMS，交给 fn 改造后写回；取不到则原样返回。"""
    lit = extract_var_literal(h, 'IX_ITEMS')
    if lit is None:
        return h
    try:
        items = json.loads(lit)
    except Exception:
        return h
    new = fn(items)
    if new is None:
        return h
    return h.replace(lit, _dumps(new), 1)


def _merge(base, patch):
    """深合并：只覆盖补丁里出现的键。"""
    out = json.loads(json.dumps(base))

    def m(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                m(dst[k], v)
            else:
                dst[k] = v
    m(out, patch)
    return out


# ------------------------------------------------------------ 结构层 B/V
@fault('删除一张内联图', 'B2', needs='img')
def f_del_img(h):
    return re.sub(r'<img[^>]*>', '', h, count=1)


@fault('截断一张图的 base64', 'V2', needs='img')
def f_cut_img(h):
    m = re.search(r'(data:image/png;base64,[A-Za-z0-9+/=]{200})', h)
    return h[:m.start()] + 'data:image/png;base64,AAAA' + h[m.end():] if m else h


@fault('插入一个外部 http 引用', 'B1,V1')
def f_ext(h):
    # B1 与 V1 是同一条结论行、同一个断言（源码层外链数 = 渲染层外链数），
    # 所以期望写两个号：期望写单个号时，覆盖率判据会以为 V1 从来没被证明过会失败。
    return h.replace('</body>', '<img src="http://example.com/a.png" alt="x"></body>', 1)


@fault('改掉内联数据集里的一个值', 'V4')
def f_data_changed(h):
    def bump(items):
        if not items:
            return None
        items[0]['title'] = str(items[0].get('title', '')) + '（改）'
        return items
    return _swap_items(h, bump)


@fault('移除 meta charset', 'B4')
def f_charset(h):
    return re.sub(r'<meta\s+charset="utf-8">', '', h, count=1, flags=re.I)


@fault('残留占位符', 'B7')
def f_placeholder(h):
    return h.replace('</body>', '<p>__TODO_ITEM__</p></body>', 1)


@fault('写入本机绝对路径', 'B6')
def f_abspath(h):
    return h.replace('</body>', '<p>C:\\Users\\someone\\a.png</p></body>', 1)


@fault('体积超过 3MB', 'B3')
def f_size(h):
    return h.replace('</body>', '<p>' + ('x' * (3 * 1024 * 1024)) + '</p></body>', 1)


@fault('B8 脚本容器里又嵌了一层 <script>', 'B8')
def f_nested_script(h):
    """复现「出件器没剥掉模板自带的 <script> 包装」这个真实故障。

    这是本轮唯一一个从成品里真找到的缺陷：离线判据当时全绿，浏览器里交互件
    一行都没执行。所以这条注入不是假想，是回归防护。
    定位方式与 f_kill_script 一致：锚定含 IX_ITEMS 的那段脚本。不能拿「第一个
    <script>」当锚——骨架在 <head> 里还有一段首屏门控脚本，嵌它不等于交互件失效。
    """
    i = h.find('IX_ITEMS')
    if i < 0:
        return h
    e = h.find('</script>', i)
    if e < 0:
        return h
    return h[:e] + '<script>/*nested*/</script>' + h[e:]


@fault('B5 页面里抛一条 console.error', 'B5')
def f_console_error(h):
    """注入一条真会被 B5 探针捕获的错误。

    探针拦 late load 之后 1.5s 内的 console.error / 未捕获异常 / unhandledrejection；
    这里放在 body 末尾，一定在探针安装之后触发，属于「能注进去且必须被判出来」的那类。
    """
    return h.replace('</body>', '<script>console.error("注入探针：这条必须被判出来");</script>'
                                '</body>', 1)


@fault('塞入超宽元素造成横向溢出', 'V5')
def f_overflow(h):
    return h.replace('</body>', '<div style="width:3000px;height:10px"></div></body>', 1)


@fault('把可见内容整体藏掉造成空白截图', 'V7')
def f_blank_page(h):
    """复现「截图判据只验头与尺寸、空白页照样 PASS」这个真实假绿。

    注入的是 CSS 而不是删内容：文本与结构原样留在源码里，所有文本/结构判据
    不受影响，变的只有「渲染出来的画面」——这正是 V7 独自守护的那一层。
    旧判据（文件存在 + 非空 + PNG 头 + 尺寸）对这张纯白截图照样全绿；
    像素校验必须把它拦下来，否则这条注入就是假绿证据。
    """
    return h.replace('</style>', 'html,body{background:#fff!important}'
                                'body>*{visibility:hidden!important}</style>', 1)


@fault('V8 最后一张卡的 data-ix 指错索引', 'V8')
def f_xindex(h):
    """复现 H3 列的那类故障：卡片索引错位，点第 k 张渲染的不是第 k 项。

    这是真实会发生的形态——卡片顺序与数据顺序由同一段循环生成，一次误改就整排错位，
    而所有静态判据（I1/I2/I3/V3/B5）都照样全绿：它们是完好无损的，只是没人点一下。
    """
    return h.replace('d.setAttribute("data-ix", i)', 'd.setAttribute("data-ix", 0)', 1)


@fault('R1 给判据族喂一个必中词', 'R1', extra=['--r1', 'PLACEHOLDER'])
def f_r1_word(h):
    """元判据 R1 的证伪：不动脚本源码，改的是**调用参数**——词表喂一个脚本里必然存在的词。

    R1 问的是「判据族源码里有没有产品分支」。以前这条没有任何注入：没法往 HTML 里注，
    于是它长期是「自认为有效、但从没被证明过」的状态。
    """
    return h


# ------------------------------------------------------------ 叙事层 N
@fault('N1 删掉一个要件且不声明 gap', 'N1')
def f_role_missing(h):
    return re.sub(r'(?s)\s*<section\b[^>]*data-role="pain"[^>]*>.*?</section>', '', h, count=1)


@fault('N2 把一个要件掏空成只剩标题', 'N2')
def f_role_hollow(h):
    def rep(m):
        attrs, inner = m.group(1), m.group(2)
        if 'data-role="method"' not in attrs:
            return m.group(0)
        head = re.search(r'(?s)<h2[^>]*>.*?</h2>', inner)
        return '<section%s>%s</section>' % (attrs, head.group(0) if head else '')
    return re.sub(r'(?s)<section\b([^>]*)>(.*?)</section>', rep, h)


@fault('N3 声明 gap 却仍保留交互件', 'N3')
def f_gap_conflict(h):
    return re.sub(r'<section(\s+data-role=")diff(")',
                  r'<section\1gap" data-gap-for="diff"\2', h, count=1)


@fault('N4 删掉全部子标题', 'N4')
def f_no_subhead(h):
    return re.sub(r'</?h[34][^>]*>', '', h)


@fault('N5 抽掉全部正文段落', 'N5')
def f_thin_text(h):
    return re.sub(r'(?s)<p>.*?</p>', '', h)


@fault('N5 计算型成品读不出数值', 'N5',
       patch={'interaction': {'pattern': 'calculator'}})
def f_no_numbers(h):
    """只抹可见文本里的数字，script/style 原样保留——不然会顺带打断 JS 数据。"""
    parts = re.split(r'(?s)(<script.*?</script>|<style.*?</style>)', h)
    out = []
    for i, p in enumerate(parts):
        if i % 2:  # 分隔符 = script/style 块
            out.append(p)
        else:
            out.append(re.sub(r'(?<![A-Za-z0-9_\-/])\d+(?:\.\d+)?(?![A-Za-z0-9_\-/])', 'n', p))
    return ''.join(out)


# ------------------------------------------------------------ 交互层 I
@fault('I1 交互件主容器丢掉默认态', 'I1')
def f_body_blank(h):
    return re.sub(r'(id="ix-body"[^>]*>)\s*—', r'\1x', h, count=1)


@fault('I2 摘掉 IX_init 调用', 'I2')
def f_noinit(h):
    """只摘调用，脚本其余部分照跑。

    所以这里只能期望 I2——V3 问的是「脚本有没有执行」，而它执行了（取证锚点仍会写入）。
    早先这条写的是 'I2,V3'，那是在 V3 缺参数静默消失的年代看不出来的错期望。
    """
    return re.sub(r'\n(\s*)IX_init\s*\(\s*\)\s*;', r'\n\1// IX_init();', h, count=1)


@fault('I2 用块注释把 IX_init 调用包起来', 'I2')
def f_noinit_block(h):
    """同一处判据的第二种失效形态。

    已有一条「行注释」版注入（`// IX_init();`）。只留那一条是不够的：判据当时只剥行注释，
    注入也只用行注释——两者共用同一个盲区，于是负向测试变成「证明它们一起错在哪」。
    判据被改成剥全部注释形态之后，必须同时留这两种形态的注入：只留一种，下次有人把判据
    改回只认那一种形态，测试照样是绿的，而漏洞回来了。
    """
    return re.sub(r'\n(\s*)IX_init\s*\(\s*\)\s*;', r'\n\1/*\n\1IX_init();\n\1*/', h, count=1)


@fault('I2/V3 整个交互件脚本被掏空', 'I2,V3')
def f_kill_script(h):
    """把含 IX_ITEMS 的脚本块整块清空：IX_init 不再定义，取证锚点也不再写入。

    一个注入同时证明两条判据——I2（IX_init 未定义/未调用）与 V3（JS 根本没执行）。
    这才是「期望多值」该有的样子：两条都真被触发，而不是靠交集判定蒙过去。
    """
    i = h.find('IX_ITEMS')
    if i < 0:
        return h
    s = h.rfind('<script', 0, i)
    e = h.find('</script>', i)
    if s < 0 or e < 0:
        return h
    return h[:s] + '<script>/*removed*/</script>' + h[e + len('</script>'):]


@fault('I3 数据项砍到 1 条', 'I3')
def f_one_item(h):
    return _swap_items(h, lambda items: items[:1] if len(items) > 1 else None)


@fault('I3 删掉一项的必填字段', 'I3')
def f_missing_field(h):
    def cut(items):
        if not items or 'key' not in items[0]:
            return None
        del items[0]['key']
        return items
    return _swap_items(h, cut)


@fault('V9 关键数字改成配置里没有的值', 'V9')
def f_stat_orphan(h):
    """数字带的数值改成一个 content.json 里没有的值——无出处的数字必须被抓住。

    成品没有渲染 stats 时这条注入不适用（返回 None → SKIP），不是成品缺陷。
    """
    m = re.search(r'(<b data-count="\d+">)(\d+)(</b>)', h)
    if not m:
        # 返回原样 = 注入不适用（本脚本的约定），由主流程判 SKIP，不是成品缺陷
        return h
    return h[:m.start(2)] + str(int(m.group(2)) + 987) + h[m.end(2):]


@fault('I4 交互件挪到声明之外的位置', 'I4')
def f_ix_moved(h):
    """把交互件挪到与声明相反的一端：原本在首位就挪到末尾，原本不在首位就挪到最前。

    只挪一个方向不够——声明 inline 的成品把交互件挪到末尾，它仍然「不在首位」，
    判据照样 PASS，那条注入就成了假绿。
    """
    blocks = [m for m in re.finditer(r'(?s)<section\b[^>]*>.*?</section>', h)]
    if len(blocks) < 2:
        return h
    ix = next((m for m in blocks if 'id="ix-body"' in m.group(0)), None)
    if ix is None:
        return h
    seg = ix.group(0)
    rest = h[:ix.start()] + h[ix.end():]
    if ix.start() == blocks[0].start():
        last = blocks[-1]
        pos = last.end() - len(seg)
        return rest[:pos] + '\n' + seg + rest[pos:]
    return rest[:blocks[0].start()] + seg + '\n' + rest[blocks[0].start():]


def _coverage_rows(a, rows):
    """CY 覆盖率：本次参数下跑得到的判据，必须各有至少一条能证明它会失败的用例。

    规矩早就写在 CONTRIBUTING.md 第一条，但没有机器守——于是 B5 与 V7 长期没有注入，
    而「21 条注入全绿」看上去什么都没缺。这里把它变成一条会 FAIL 的判据：
      · 跑得到的判据没有注入 → FAIL（点名缺哪条）；
      · 属于 UNIT_PROVEN（注入动不了它）的判据 → 真的去跑一次 `check_demo --self-test`，
        跑不过就是 FAIL。不是嘴上说「有单测」，是当场证明。
        （该名单现在为空：V7 补上像素校验后注入动得了它，已拉回注入路径。）
    """
    covered = set()
    for name, expect, _fn, _patch, _needs, _extra in FAULTS:
        ids = set(x.strip() for x in expect.split(',') if x.strip())
        # 期望的全部判据在本轮参数下都跑不到时，这条用例这轮什么都不证明，不计入覆盖
        if all(_missing_arg(cid, a) for cid in ids):
            continue
        covered |= ids
    out = []
    need_unit = []
    for cid in sorted(CRITERIA_ARGS):
        if cid in covered:
            continue
        if cid in UNIT_PROVEN:
            # 这类判据的「能被证明会失败」与本次有没有跑无关，所以每轮都验，
            # 不藏在「只有给全参数才会检查」的角落里。
            need_unit.append(cid)
        elif not _missing_arg(cid, a):
            # 本次参数下会真的执行，却没有注入用例——这条判据目前只是自认为有效
            out.append(('注入覆盖率缺口：%s' % cid, cid,
                        '本次参数下 %s 会执行，却没有注入用例证明它会失败' % cid, 'FAIL'))
        # 其余：本次参数下跑不到，谈不上覆盖率（核验器那边会列 SKIP）
    if need_unit:
        try:
            r = subprocess.run([sys.executable, CHECK, '--self-test'],
                               capture_output=True, timeout=120)
            passed = (r.returncode == 0
                      and '单测结论：PASS' in r.stdout.decode('utf-8', 'replace'))
        except Exception:
            passed = False
        for cid in need_unit:
            if passed:
                out.append(('注入覆盖率：%s 由单测证明' % cid, cid,
                            'HTML 注入动不了它（它判的是浏览器产物的二进制），'
                            '改由 check_demo --self-test 的纯函数用例证明会失败', 'PASS'))
            else:
                out.append(('注入覆盖率：%s 缺证明' % cid, cid,
                            '既无 HTML 注入，且 check_demo --self-test 未通过', 'FAIL'))
    if not out:
        # 全覆盖时一行都不出，这条判据就自己「静默消失」了——与它专门抓的病同形。
        # 出席必须自己也得守：不出结论行的判据，凭什么判别人缺席。
        ran = [cid for cid in CRITERIA_ARGS if not _missing_arg(cid, a)]
        out.append(('CY 覆盖率：本次跑得到的 %d 条判据条条有注入证明' % len(ran), 'CY',
                    '覆盖率判据自己也要出席（全覆盖时同样要出结论行）', 'PASS'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html')
    ap.add_argument('--profile')
    ap.add_argument('--data')
    ap.add_argument('--img', type=int, default=None)
    ap.add_argument('--js-value')
    ap.add_argument('--chrome')
    ap.add_argument('--shot')
    ap.add_argument('--workdir')
    ap.add_argument('--json')
    a = ap.parse_args()

    work = a.workdir or os.path.join(os.path.dirname(os.path.abspath(a.html)), '_negtest')
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work, exist_ok=True)
    if a.chrome and not a.shot:
        # V7 要 --shot 才跑得起。截图是本脚本的内部取证产物，不该让调用者手工备——
        # 不自动备的话，V7 在覆盖率里就成了「跑得到却永远没有注入」的判据。
        a.shot = os.path.join(work, '_v7.png')
    src = open(a.html, encoding='utf-8').read()

    prof, pdir = None, ''
    if a.profile:
        pdir = os.path.dirname(os.path.abspath(a.profile))
        prof = json.loads(open(a.profile, encoding='utf-8').read())

    rows, bad = [], []
    for idx, (name, expect, fn, patch, needs, extra) in enumerate(FAULTS):
        mutated = fn(src)
        if mutated == src and extra:
            # extra 型注入不改 HTML（改的是调用参数），不能按「未生效」处理
            pass
        elif mutated == src:
            # 注入不进去有两种成因，必须分开报，否则会把测量条件缺失说成成品缺陷：
            #   ① 契约明确要求该特征（--img N>0）却找不到 → 成品缺陷，判 FAIL；
            #   ② 成品形态本就不含该特征（--img 0，例如交互件走无图形态）→ 测量条件
            #      不成立，判 SKIP（与下方「需 --chrome，未验证」同一原则：不让缺条件
            #      冒充通过，也不让缺条件冒充失败）。
            if needs == 'img' and a.img is not None and a.img > 0:
                rows.append((name, expect,
                             '注入未生效：契约要求 %d 张内联图，成品里没有可注入的点' % a.img,
                             'FAIL'))
                bad.append(name)
            else:
                rows.append((name, expect,
                             '跳过：成品形态不含该注入点，该注入不适用（本条未验证）',
                             'SKIP'))
            continue
        # 期望判据支持多值（逗号分隔）：同一处注入往往能同时证明离线判据与浏览器判据。
        # 只有「所有期望都跑不到」时才整条跳过；能跑一部分就跑，跑不到的期望在结论里点名。
        want = set(x.strip() for x in expect.split(',') if x.strip())
        unver = unverifiable_ids(want, a)
        if unver and len(unver) == len(want):
            rows.append((name, expect,
                         '未验证：%s' % '；'.join('%s 需 %s' % (w, r) for w, r in unver),
                         'SKIP'))
            continue
        prof_arg = a.profile
        if patch:
            if not prof:
                rows.append((name, expect, '该注入要改判据分档，需 --profile，未验证', 'SKIP'))
                continue
            patched = _merge(prof, patch)
            inter = patched.get('interaction') or {}
            if inter.get('data') and not os.path.isabs(inter['data']):
                # 补丁文件落在临时目录，数据源指针改成绝对路径才找得到
                inter['data'] = os.path.join(pdir, inter['data'])
            prof_arg = os.path.join(work, 'profile_patched.json')
            with open(prof_arg, 'w', encoding='utf-8') as f:
                json.dump(patched, f, ensure_ascii=False, indent=2)

        p = os.path.join(work, 'fault_%02d_%s.html' % (idx + 1, expect))
        open(p, 'w', encoding='utf-8', newline='\n').write(mutated)
        cmd = [sys.executable, CHECK, p]
        if prof_arg:
            cmd += ['--profile', prof_arg]
        if a.data:
            cmd += ['--data', a.data]
        if a.img is not None:
            cmd += ['--img', str(a.img)]
        if a.js_value:
            cmd += ['--js-value', a.js_value]
        if a.chrome:
            cmd += ['--chrome', a.chrome]
        if a.shot:
            cmd += ['--shot', a.shot]
        if extra:
            cmd += extra
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        out = r.stdout.decode('utf-8', 'replace')
        # 一条结论行可能属于多条判据（"B1/V1 …"）——把整组号都取出来，
        # 否则分组里的第二条永远看不到自己被命中。
        failed_ids = set()
        for grp in re.findall(r'^FAIL\s+((?:[A-Z]\d/?)+)', out, re.M):
            failed_ids |= set(re.findall(r'[A-Z]\d', grp))
        verdict, note = judge(r.returncode, want, failed_ids, unver)
        rows.append((name, expect, note, verdict))
        if verdict in ('FAIL', 'WARN'):
            bad.append(name)

    rows += _coverage_rows(a, rows)
    bad = [n for n, _e, _c, v in rows if v in ('FAIL', 'WARN')]
    ok = not bad

    print('%-34s %-6s %-8s %s' % ('故障注入', '期望', '结论', '说明'))
    for n, e, c, v in rows:
        print('%-34s %-6s %-8s %s' % (n[:34], e, v, c))
    nskip = len([r for r in rows if r[3] == 'SKIP'])
    npass = len([r for r in rows if r[3] == 'PASS'])
    print('\nV6 负向测试：%s（%d 条用例：通过 %d / 问题 %d / 跳过 %d）'
          % ('PASS' if ok else 'FAIL', len(rows), npass, len(bad), nskip))
    if nskip:
        print('        跳过不等于通过——下列用例在本次成品形态下没有被执行：')
        for n, e, c, v in rows:
            if v == 'SKIP':
                print('          · %s（期望 %s）：%s' % (n, e, c))
    if bad:
        print('        有问题需要修：')
        for n in bad:
            print('          · %s' % n)
    if a.json:
        json.dump({'rows': rows, 'pass': ok}, open(a.json, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
