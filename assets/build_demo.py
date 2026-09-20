#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""演示件出件器：项目配置 + 版式骨架 + 所选交互件模板 → 单文件自包含 HTML。

用法：
  python build_demo.py --profile profiles/<产品>/profile.json --out <成品.html>
  可选：--skeleton <骨架路径>（默认用本目录下的 template_skeleton.html）
        --assets-dir <素材目录>（默认取 profile.json 的 assets_dir）

设计目的：
  1. 模板与注入分离——禁止直接手写含 base64 的超大文件。
  2. 本体与产品分离——本文件不得出现任何产品名或产品专有字段名；
     产品差异全部来自 profile.json / content.json / 交互件数据文件。

装配顺序（顺序不能改）：
  先给交互件模板填空（模板里的 IX_* 占位符），再把填好的整段包成带 data-role 的
  section 替换 sections.html 里的 <!--INTERACTION-->，最后整段注入骨架。
  反过来的话，模板里没填的占位符会混进成品，而残留检查是在最后一步做的。
"""
import argparse
import base64
import json
import os
import re
import sys

PLACEHOLDER = re.compile(r'__(?:[A-Z][A-Z0-9_]{2,})__')
MARKER = '<!--INTERACTION-->'
ROLES = ('pain', 'method', 'evidence', 'diff', 'boundary', 'gap')
SECTIONS = {
    'css':  re.compile(r'<!--css-->(.*?)<!--html-->', re.S),
    'html': re.compile(r'<!--html-->(.*?)<!--js-->', re.S),
    'js':   re.compile(r'<!--js-->(.*)', re.S),
}


def b64(path):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


def sha256_of(p):
    """素材指纹：打印出来是为了让「这次取的是哪一份」可回读。"""
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(65536), b''):
            h.update(blk)
    return h.hexdigest()[:12]


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def load_json(p):
    """读配置/数据包：读不到、或不是合法 JSON，都给明确中止。

    不抛裸回溯——回溯只说明 Python 崩了，不说明用户该改哪里。
    （给目录时 open() 报 PermissionError / IsADirectoryError，两者都是 OSError。）
    """
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except OSError as e:
        die('读不到 %s（%s）' % (p, e))
    except ValueError as e:
        die('%s 不是合法 JSON（%s）' % (p, e))


def as_dict(payload, path, what):
    """JSON 合法但形状不对，是最后一类没被覆盖的错误。

    「读不到 / 不是合法 JSON」两例早已有明确提示，剩下的是「合法 JSON 但不是这个形状」：
    数据源写成顶层数组时 `payload.get(...)` 会抛 AttributeError 裸回溯；
    content.json 缺 brand 时 `content['brand']` 抛 KeyError 裸回溯。
    逐个补 try 是打地鼠——这里统一走一处形状校验，缺什么就说什么。
    """
    if not isinstance(payload, dict):
        die('%s 的顶层不是 JSON 对象（%s）：top-level 是 %s，应为 {…}'
            % (path, what, type(payload).__name__))
    return payload


def need_key(d, key, path, what):
    if key not in d or d[key] in (None, ''):
        die('%s 缺 %s（%s）—— 缺了它出件器只能静默出一份空壳，所以这里直接中止'
            % (path, key, what))
    return d[key]


def need_sub(d, key, path, what, sub):
    v = need_key(d, key, path, what)
    if not isinstance(v, dict):
        die('%s 的 %s 不是对象（应为 {…}），实际是 %s' % (path, key, type(v).__name__))
    return need_key(v, sub, path, '%s 的 %s 缺' % (what, key))


def die(msg):
    sys.stderr.write('出件中止：%s\n' % msg)
    sys.exit(2)


def split_template(text, path):
    """按三段式标记切分交互件模板。缺任何一段都算模板不完整，直接中止。"""
    out = {}
    for key, rx in SECTIONS.items():
        m = rx.search(text)
        if not m:
            die('交互件模板不完整（缺 %s 段标记）：%s' % (key, path))
        out[key] = m.group(1).strip('\n')
    return out


def strip_tag_wrapper(seg, tag):
    """剥掉交互件模板自带的首尾 <tag>…</tag> 包装。

    骨架已提供同名容器（一个 <style> 槽、一个 <script> 槽），模板再带一层就形成
    嵌套标签。对 <script> 是致命的：浏览器在第一个 </script> 处截断，脚本内容变成
    「注释 + <script> + 真正的代码」，直接语法错误，整个块一行都不执行——
    表现是交互件毫无反应，而源码看起来毫无问题。
    """
    seg = re.sub(r'^\s*<%s\b[^>]*>' % tag, '', seg, count=1)
    seg = re.sub(r'</%s\s*>\s*$' % tag, '', seg, count=1)
    return seg


def validate_roles(sections):
    """每段必须声明 data-role，且取值在允许集合内——判据按这个属性做断言。"""
    bad = []
    for m in re.finditer(r'<section\b([^>]*)>', sections):
        rm = re.search(r'data-role\s*=\s*"([^"]*)"', m.group(1))
        if not rm:
            bad.append('未声明 data-role')
        elif rm.group(1) not in ROLES:
            bad.append(rm.group(1))
    if bad:
        die('sections 存在非法/缺失的 data-role：%s；允许值 %s'
            % (', '.join(bad[:6]), '/'.join(ROLES)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', required=True, help='profiles/<产品>/profile.json')
    ap.add_argument('--skeleton', default='', help='默认取本目录 template_skeleton.html')
    ap.add_argument('--assets-dir', default='', help='默认取 profile.json 的 assets_dir')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    pdir = os.path.dirname(os.path.abspath(a.profile))
    if os.path.isdir(a.profile):
        die('--profile 要的是 profile.json 这个文件，不是目录：%s\n'
            '  正确写法：--profile %s/profile.json'
            % (a.profile, a.profile.rstrip('/\\')))
    prof = as_dict(load_json(a.profile), a.profile, 'profile.json')

    def need(rel):
        """内容包缺件时给明确提示——不许静默出一份空壳。"""
        p = rel if os.path.isabs(rel) else os.path.join(pdir, rel)
        if not os.path.isfile(p):
            die('内容包缺件：%s（profile 声明了 %s，但磁盘上没有）'
                % (p, os.path.basename(rel)))
        return p

    content = as_dict(load_json(need(prof.get('content', 'content.json'))),
                      prof.get('content', 'content.json'), 'content.json')
    sections = read(need(prof.get('sections', 'sections.html')))
    # 品牌色只从 content.json 取，所以出件前先把必填项验掉：
    # 缺 brand / 缺 primary 在旧实现里是 KeyError 裸回溯，看不出该改哪个文件。
    need_sub(content, 'brand', prof.get('content', 'content.json'), 'content.json', 'primary')
    for k in ('doc_title', 'hero_title'):
        need_key(content, k, prof.get('content', 'content.json'), 'content.json 的文案')

    # ---- 交互件：类型与数据由 profile 声明，叙事标题由 content 声明 ----
    inter = prof.get('interaction') or {}
    ix_css, ix_html, ix_js = '', '', ''
    pattern = inter.get('pattern')
    if pattern:
        tpath = os.path.join(here, 'interactions', pattern + '.html')
        if not os.path.isfile(tpath):
            die('profile 声明的交互件模板不存在：%s（可选 calculator / catalog）' % tpath)
        # 形态判定此前是纯人工自证：_why 写「为什么是这个形态」，但没有任何一处校验它存在。
        # 四类形态只有两份模板，判错形态 = 交互件根本不对题；没写依据的声明等于拍脑袋。
        if not str(inter.get('_why') or '').strip():
            die('profile 声明了 interaction.pattern=%r 却没填 interaction._why ——'
                '形态是按「参数→数值」还是「问题→样例」定的必须写出依据'
                '（判定表见 assets/interaction_patterns.md）' % pattern)
        if not inter.get('data'):
            die('profile 声明了 interaction.pattern 但未给 interaction.data')
        payload = as_dict(load_json(need(inter['data'])), inter['data'], '交互件数据源')
        raw_items = payload.get('items')
        if raw_items is None:
            raw_items = payload.get('cases')
        if raw_items is None:
            die('%s 里既没有 items 也没有 cases（交互件数据源必须给其中一组）' % inter['data'])
        if not isinstance(raw_items, list):
            die('%s 的 items 不是数组（应为 [ … ]），实际是 %s'
                % (inter['data'], type(raw_items).__name__))
        items = raw_items
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                die('%s 的第 %d 条数据不是对象（应为 {…}），实际是 %s'
                    % (inter['data'], i + 1, type(it).__name__))
        if len(items) < 2:
            die('交互件数据项数 %d < 2，不构成对照——按交互形态分类表应改标 gap 段，'
                '而不是放一个空转的交互件' % len(items))
        axis = payload.get('axis') or {}
        ix_content = content.get('interaction') or {}
        parts = split_template(read(tpath), tpath)
        fill = {
            '__IX_ITEMS__': json.dumps(items, ensure_ascii=False, separators=(',', ':')),
            '__IX_AXIS__': json.dumps([axis.get('lo'), axis.get('hi')],
                                      ensure_ascii=False, separators=(',', ':')),
            '__IX_UNIT__': json.dumps(ix_content.get('unit', ''), ensure_ascii=False),
            '__IX_STEP_LABEL__': json.dumps(ix_content.get('step_label', ''), ensure_ascii=False),
        }
        for key in ('css', 'html', 'js'):
            val = parts[key]
            for k, v in fill.items():
                val = val.replace(k, v)
            if key == 'css':
                ix_css = strip_tag_wrapper(val, 'style')
            elif key == 'js':
                ix_js = strip_tag_wrapper(val, 'script')
            else:
                ix_html = val
        if MARKER not in sections:
            die('profile 声明了交互件，但 sections 里找不到 %s 标记——交互件会被静默丢掉' % MARKER)
        ix_section = (
            '<section data-role="%s">\n'
            '    <h2>%s</h2>\n'
            '    <div class="sub">%s</div>\n%s\n  </section>'
            % (inter.get('role', 'evidence'), ix_content.get('title', ''),
               ix_content.get('sub', ''), ix_html))
        # 装配位置由 interaction.position 声明：默认 front —— 交互件提到所有分节之前，
        # 叙事从「先读完再玩」改成「先玩后读」。写 inline 则按 sections 里的标记位置原地插入。
        pos = str(inter.get('position', 'front')).lower()
        if pos not in ('front', 'inline'):
            die('interaction.position=%r 未登记（可选 front / inline）' % inter.get('position'))
        if pos == 'front':
            sections = ix_section + '\n' + sections.replace(MARKER, '').lstrip('\n')
        else:
            sections = sections.replace(MARKER, ix_section)
    elif MARKER in sections:
        die('sections 里留了 %s 标记，但 profile 未声明 interaction.pattern' % MARKER)

    validate_roles(sections)

    # ---- 版式注入 ----
    b = content['brand']
    mapping = {
        '__DOC_TITLE__': content['doc_title'],
        '__PRODUCT_NAME__': content['product_name'],
        '__HEADER_TAGLINE__': content.get('header_tagline', ''),
        '__HERO_TITLE__': content['hero_title'],
        '__HERO_LEAD__': content['hero_lead'],
        '__SECTIONS_HTML__': sections,
        '__FOOTER_NOTE__': content.get('footer_note', prof.get('footer_note', '')),
        '__INTERACTION_CSS__': ix_css,
        '__INTERACTION_JS__': ix_js,
        '__BRAND_PRIMARY__': b['primary'],
        '__BRAND_DARK__': b.get('brand_dark', b['primary']),
        '__BRAND_LIGHT__': b.get('brand_light', '#EEF1FA'),
        '__BRAND_ACCENT__': b.get('accent', b['primary']),
        '__INK__': b.get('ink', '#222222'),
        '__INK_2__': b.get('ink_2', '#666666'),
        '__LINE__': b.get('line', '#DDDDDD'),
    }
    tpl = read(a.skeleton or os.path.join(here, 'template_skeleton.html'))

    # ---- 可选素材：未提供则整块移除 ----
    # 素材目录解析：填相对路径时按 **profile 所在目录** 解析。此前相对路径是按当前工作目录
    # 解析的——从仓根跑和从别的目录跑，拿到的可能是两份不同的图。
    # 两种情况都把最终路径 + sha256 前 12 位打印出来：「这次取的是哪一份」必须可回读，
    # 否则素材目录被技能升级覆盖一次，成品里的图就悄悄换了而没有任何判据会发现。
    adir_cfg = a.assets_dir or prof.get('assets_dir', '')
    adir = adir_cfg if os.path.isabs(adir_cfg) else os.path.join(pdir, adir_cfg)
    if adir_cfg and os.path.abspath(adir) != os.path.abspath(pdir):
        sys.stderr.write('提示：素材取自 profile 目录之外（%s）——这个目录被升级/重装换掉时，'
                         '成品里的图会静默变化；本行路径与 sha256 是回读依据\n' % adir)
    # 骨架用 <!--ASSET:key-->…<!--/ASSET:key--> 包住可选元素。早期版本把 logo / hero
    # 写成固定元素，于是「没有 logo 的产品出不了件」——可选素材被当成必需素材，
    # 还逼得最小示例必须塞两张假图。改标记包法后，留空即不出图。
    for key in ('logo', 'hero'):
        ob, cb = '<!--ASSET:%s-->' % key, '<!--/ASSET:%s-->' % key
        rel = (prof.get('assets') or {}).get(key) or ''
        if ob not in tpl:
            # 提供了图却没有插入位 = 图片被静默丢掉。宁可中止也不许静默。
            if rel:
                die('骨架缺少 <!--ASSET:%s--> 插入位，profile.assets.%s 的图会被静默忽略'
                    % (key, key))
            continue
        rx = re.compile(r'(?s)%s(.*?)%s[ \t]*\n?' % (re.escape(ob), re.escape(cb)))
        if rel:
            img = os.path.join(adir, rel)
            if not os.path.isfile(img):
                die('素材缺失：%s（profile.assets.%s 指向的图片不在磁盘上）' % (img, key))
            mapping['__%s_B64__' % key.upper()] = b64(img)
            print('素材 %-4s %s  sha256 %s' % (key, img, sha256_of(img)))
            tpl = rx.sub(lambda m: m.group(1), tpl, count=1)
        else:
            tpl = rx.sub('', tpl, count=1)

    # 「先玩一下」入口只在真的有交互件时出现；没有交互件却留着这个按钮 = 点了没地方可玩。
    pob, pcb = '<!--PLAY-->', '<!--/PLAY-->'
    if pob in tpl:
        prx = re.compile(r'(?s)%s(.*?)%s[ \t]*\n?' % (re.escape(pob), re.escape(pcb)))
        if pattern:
            tpl = prx.sub(lambda m: m.group(1), tpl, count=1)
        else:
            tpl = prx.sub('', tpl, count=1)
    elif pattern:
        sys.stderr.write('提示：骨架缺少 %s 插入位，首屏不会给出「先玩一下」入口\n' % pob)

    # ---- 关键数字区：可选。content.stats 给了才出，没给整块移除 ----
    # 数字终值与条的终宽都写进标签与行内 style：脚本不跑时它们本来就是终态。
    stats = content.get('stats') or []
    if not isinstance(stats, list):
        die('content.json 的 stats 不是数组（应为 [ … ]），实际是 %s'
            % type(stats).__name__)
    if stats:
        vals = []
        for i, st in enumerate(stats):
            if not isinstance(st, dict):
                die('content.json 的 stats 第 %d 条不是对象（应为 {value,label}）' % (i + 1))
            v = st.get('value')
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                die('content.json 的 stats 第 %d 条缺数值型的 value（条宽按它归一，'
                    '给不出就没法画条）' % (i + 1))
            if not str(st.get('label') or '').strip():
                die('content.json 的 stats 第 %d 条缺 label' % (i + 1))
            vals.append(v)
        mx = max(vals)
        cells = []
        for v, st in zip(vals, stats):
            pct = int(round(v / mx * 100)) if mx else 0
            cells.append('<div class="stat"><b data-count="%g">%g</b>'
                         '<span class="lb">%s</span>'
                         '<i class="bar" data-grow="%d%%" style="width:%d%%"></i></div>'
                         % (v, v, st['label'], pct, pct))
        stats_html = ('\n    <div class="stats">\n      ' + '\n      '.join(cells)
                      + '\n    </div>')
    else:
        stats_html = ''
    if '<!--STATS-->' not in tpl:
        if stats:
            die('骨架缺少 <!--STATS--> 插入位，content.json 的 stats 会被静默忽略')
    else:
        tpl = tpl.replace('<!--STATS-->', stats_html)

    # profile.json 里的 brand 不生效（品牌色取自 content.json）——提示而不是静默，
    # 否则「改了配色却不生效」会变成一个查不出原因的坑。
    if prof.get('brand'):
        sys.stderr.write('提示：profile.json 的 brand 字段不生效，品牌色以 content.json 的 brand 为准'
                         '（该字段仅作历史留存，可删）\n')

    for k, v in mapping.items():
        tpl = tpl.replace(k, v)

    left = sorted(set(PLACEHOLDER.findall(tpl)))
    if left:
        die('仍有未替换占位符 %s（新增占位符须先在本出件器登记）' % ', '.join(left))

    # 出件后自检：脚本/样式标签必须配对且不嵌套。
    # 嵌套 <script> 会让整个脚本块静默不执行——那正是「离线判据全绿、交互件完全不工作」
    # 的典型成因，所以在出件这一步就拦下，不等核验环节。
    for tag, seg in (('script', 'js'), ('style', 'css')):
        o = len(re.findall(r'<%s\b[^>]*>' % tag, tpl))
        c = len(re.findall(r'</%s\s*>' % tag, tpl))
        if o != c:
            die('成品 <%s> 标签不配对（开 %d / 闭 %d）' % (tag, o, c))
        for m in re.finditer(r'(?s)<%s\b[^>]*>(.*?)</%s\s*>' % (tag, tag), tpl):
            if re.search(r'</?%s\b' % tag, m.group(1)):
                die('成品出现嵌套 <%s>：交互件模板的 %s 段重复包了一层 <%s>，出件器未剥离'
                    % (tag, seg, tag))

    out_dir = os.path.dirname(a.out)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(tpl)
    print('出件：%s（%d 字节，交互件 %s，section %d 段）'
          % (a.out, os.path.getsize(a.out), pattern or '无',
             len(re.findall(r'<section\b', tpl))))


if __name__ == '__main__':
    main()
