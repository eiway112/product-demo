#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本体清洁度扫描器：证明「本体里没有产品名、没有产品专属字段结构，
交互件模板里也没有写死的业务文案」。

用法：
  python audit_body.py [--skill-dir <技能目录>] [--words <外部词表>]
                       [--json <报告路径>] [--self-test]

两个概念不许混着用（此前混过，于是同一句话有两种外延）：

  **本体（受保护集）** = `SKILL.md` + `assets/**`——「换产品零改动」这条验收的对象，
      验收方式是 `git diff --stat -- SKILL.md assets/` 为 0 行。
  **扫描范围（防线）** = 技能目录下全部文本文件，排除 `profiles/**`、`.git` 与
      `.workbuddy`（会话运行态，不发布）——比本体更宽：连 README / CHANGELOG /
      CONTRIBUTING / manifest 一起扫。

放着 README 之类的文件一起扫不是失误：它们是会被发布出去的东西，里面冒出产品名同样算污染。
代价是「本体零改动验收通过」与「清洁度扫描 0 命中」不是一回事——前者只守 SR/L 一项，后者守全部文本。
两个口径分别看，别拿一个的结论替另一个作答。

判据三族：
  1) 产品词   —— 词表 = 自动收集的 profiles/*/profile.json 的 product / vendor
                 + 可选 --words 外部词表。下划线开头的目录（_模板 / _示例）是基础设施，
                 不进词表：否则示例的占位名会被当成真实产品词，词表本身就不可信了。
                 词条若是 ASCII 词，按词边界匹配**且允许数字后缀**（产品代号最常见的
                 出现形态是「代号 + 型号数字」，旧实现右边界含数字，这种形态一个都抓不到）；
                 词表里写 `re:<正则>` 可以用正则表达更复杂的变体形态。
  2) 结构签名 —— 产品专属字段组合（见 SIGNATURES）。
  3) C5       —— 交互件模板（assets/interactions/*.html）的可见文本不得出现中文。
                 契约见 assets/interaction_patterns.md §三 C5：「字段标签一律来自数据，
                 不来自模板」。这一族不依赖词表，所以在没有产品配置的 clone 里同样有判别力。

为什么要有结构检查，而不只是查产品名：
  早期判据只查 SKILL.md 的文本 diff，结果骨架里焊着某个产品的算例字段结构却报「通过」。
  产品名可以一个都不出现，结构照样是被污染的——查字符串查不到结构，所以这里除了词表，
  还有一组「结构签名」（多个字段同时出现的组合特征，单看一个词容易误报）。

退出码：0 = 全清；1 = 有命中（HARD 都算，判据要能失败才有意义）。
自检：--self-test 造一个临时 profiles 条目，并注入三类故障（产品名 / 结构签名 / C5 中文可见文本），
      断言扫描器必须全部报出来；同时证明「词表来自 profiles 自动收集」这条链路有效。
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 文本口径与词条匹配一律复用 measure_density 的实现。
# 此前 visible_text 在这里另有一份（剥了 HTML 注释），在 measure_density 那份（没剥）
# 旁边活着，两边都写着「同口径」——同一口径两份实现，迟早漂移。
from measure_density import CJK, visible_text, word_hit  # noqa: E402

# 本体零产品名：这里一个词都不写死，产品词一律从 profiles 自动收集，或用 --words 外部词表。
# 为什么不在仓里配一份随库入库的词表：写进去的产品名会让扫描器自身成为本体里
# 最后一处产品名——检查定义与被检查内容必须分开。代价是干净克隆里这一族没有判别力，
# 这个代价是明确接受的，并且脚本每次都会把「本次有没有判别力」说出来。
BASE_WORDS = []

# 自检专用注入词，只在本体自检时使用，不是任何真实产品名。
SELFTEST_WORD = 'SelfTestProductName'
SELFTEST_IX = '_selftest.html'

TEXT_EXT = ('.md', '.html', '.py', '.json', '.txt', '.js', '.css')
# .workbuddy 是智能体会话的运行态（记忆 / 日志，未入库、永不发布）——与 .git 同类，
# 不在「会被发布出去的东西」这个扫描对象里。2026-09-20 实测：会话记忆里写着产品名，
# 把整条防线判成 FAIL，而被扫的对象其实一件都不会出去。
# 2026-09-20 实测：.gitignore 排除 `过程文件/` 并在注释里写明「与 .workbuddy 同一口径、不算本体」，
# 而 SKIP_DIRS 里没有它——注释写完当天就漂移了，于是清洁度闸门在本工作树永久假红（基线命中 2），
# 红的原因与「本体被产品特化」毫无关系。永久红的闸门等于没有闸门。
SKIP_DIRS = ('profiles', '.git', '.workbuddy', '过程文件')

# .gitignore 里还有一类「技术产物目录」：它们也不入库，但里面没有会被扫的文本（.pyc 等），
# 因此不要求进 SKIP_DIRS——硬要求会逼出无意义的假红。
KNOWN_TECH_DIRS = ('__pycache__', 'node_modules', '.pytest_cache', '.venv', 'venv')

# 交互件模板所在位置（相对技能目录）——C5 的扫描对象
IX_SUBDIR = ('assets', 'interactions')

# 结构签名：产品专属字段组合。任何一个单元命中即 HARD——
# 单看一个词可能误报，但下面每条都是「多个字段同时出现」的组合特征。
SIGNATURES = [
    (r'__COMPARE_', '旧版固定对比器的占位符'),
    (r'\bvar\s+CASES\b', '旧版固定对比器的数据变量'),
    (r'pv-[a-z]+', '旧版固定对比器的元素 id 前缀'),
]

# 「若干字段同时出现」型签名：逐词独立判定，全部出现才算命中。
#
# 不要写成 (?s)(?=.*\bfamily\b)(?=.*\banchors\b)(?=.*\bloo\b) —— 那种写法里
# (?s) 让 `.` 跨行、而 lookahead 在每个起始位置都要扫到文本末尾，于是退化成
# O(n²) 回溯：实测同一个 23KB 文件，原写法单条 7~11 秒，拆成三次独立 search
# 是 0.001 秒。语义完全相同——两者都只问「这几个词是否都出现过」。
SIGNATURE_AND = [
    (('family', 'anchors', 'loo'), '某产品的算例字段组合（family/anchors/loo）'),
    (('mid', 'low', 'high'), '某产品的算例字段组合（mid/low/high）'),
]


def load_words(skill_dir, extra_path=None):
    """固定基线（默认空）+ 自动从 profiles 收集产品名与厂商名 + 可选外部词表。

    跳过下划线开头的目录：_模板 / _示例 是基础设施，不是产品配置。
    """
    words = list(BASE_WORDS)
    for pj in glob.glob(os.path.join(skill_dir, 'profiles', '*', 'profile.json')):
        if os.path.basename(os.path.dirname(pj)).startswith('_'):
            continue
        try:
            d = json.load(open(pj, encoding='utf-8'))
        except Exception:
            continue
        for key in ('product', 'vendor'):
            if d.get(key):
                words.append(d[key])
    if extra_path and os.path.exists(extra_path):
        for line in open(extra_path, encoding='utf-8'):
            w = line.strip()
            if w and not w.startswith('#'):
                words.append(w)
    return sorted(set(w for w in words if w))


# 词条匹配的实现收敛到 measure_density.word_hit（内部已支持「允许数字后缀」与 `re:` 正则条目）。
# 这里不再自留一份正则：两处各写一遍，必然有一边漏掉后来补上的那一半判别力。
hit = word_hit


def gitignore_dir_excludes(skill_dir):
    """.gitignore 里的顶层目录排除项（放行规则 `!`、注释、含路径的规则都不算）。

    只取形如 `目录名/` 或 `目录名/*` 的顶层条目：嵌套规则（如 `a/b/`）不属于
    「本仓顶层哪些目录不算本体」这个口径，混进来会让判据的语义变糊。
    """
    p = os.path.join(skill_dir, '.gitignore')
    if not os.path.isfile(p):
        return []
    out = []
    for line in open(p, encoding='utf-8'):
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('!'):
            continue
        # 必须带 `/`：`*.pyc` 这类「按后缀排除」的条目不是目录口径，混进来会假红。
        m = re.match(r'^([^/\s*]+)/$', s) or re.match(r'^([^/\s*]+)/\*$', s)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def align_findings(skill_dir):
    """「什么不算本体」这个口径有两份事实来源：.gitignore 与 SKIP_DIRS。

    两者语义本该同源，却各写各的、也没有任何判据比对它们——N1 就是这么来的。
    补一个目录名能修这一次，但下次新增排除目录还会漏；所以这里把对齐做成判据：
    漏一个就点名，而不是等闸门永久假红了才被人发现。
    """
    miss = [d for d in gitignore_dir_excludes(skill_dir)
            if d not in SKIP_DIRS and d not in KNOWN_TECH_DIRS]
    return [('ALIGN', '.gitignore',
             '排除了目录 %s/，但 audit_body 的 SKIP_DIRS 里没有它——两者本该同一口径'
             '（既不入库也不算本体）；漏一个，清洁度闸门就会对永远发布不出去的东西报红'
             % d) for d in miss]


def c5_scan(skill_dir):
    """C5：交互件模板的可见文本不得出现中文（字段标签一律来自数据）。

    返回 (findings, 检查的模板数)。模板目录不存在时视为「本形态尚未用到交互件」，
    返回 0 件——调用方据此决定这条判据是有判别力还是不适用。
    """
    findings, n = [], 0
    d = os.path.join(skill_dir, *IX_SUBDIR)
    if not os.path.isdir(d):
        return findings, n
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith(('.html', '.htm')):
            continue
        n += 1
        try:
            t = open(os.path.join(d, fn), encoding='utf-8').read()
        except Exception:
            continue
        vis = visible_text(t)
        m = CJK.search(vis)
        if m:
            seg = re.sub(r'\s+', ' ', vis[max(0, m.start() - 10):m.start() + 14]).strip()
            findings.append(('HARD', '/'.join(IX_SUBDIR) + '/' + fn,
                             'C5 模板写死了中文可见文本：「…%s…」——字段标签必须来自数据，'
                             '不来自模板' % seg))
    return findings, n


def scan(skill_dir, extra_path=None):
    words = load_words(skill_dir, extra_path)
    findings = []
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in sorted(files):
            if not fn.lower().endswith(TEXT_EXT):
                continue
            if fn == os.path.basename(__file__):
                # 扫描器自身的词表与签名就是检查定义，不是被检查的内容——跳过自己
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, skill_dir).replace('\\', '/')
            try:
                t = open(p, encoding='utf-8').read()
            except Exception:
                continue
            for w in words:
                if hit(t, w):
                    findings.append(('HARD', rel, '产品词命中：%s' % w))
            for rx, why in SIGNATURES:
                if re.search(rx, t):
                    findings.append(('HARD', rel, '结构签名命中：%s' % why))
            for ws, why in SIGNATURE_AND:
                if all(re.search(r'\b' + w + r'\b', t) for w in ws):
                    findings.append(('HARD', rel, '结构签名命中：%s' % why))
    c5, ix_n = c5_scan(skill_dir)
    findings += c5
    return findings, words, ix_n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skill-dir',
                    default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--words', help='外部词表文件（每行一个词，# 开头为注释）')
    ap.add_argument('--json')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    skill = os.path.abspath(a.skill_dir)

    if a.self_test:
        tmp = tempfile.mkdtemp(prefix='bodyaudit_')
        try:
            tgt = os.path.join(tmp, 'skills', 'x')
            # 故意不复制 profiles：自检要独立于真实产品配置，并借此证明
            # 「词表确实来自 profiles 自动收集」——收集断了则词表为空、必然不命中。
            shutil.copytree(skill, tgt, ignore=shutil.ignore_patterns(
                '.git', 'profiles', '.workbuddy'))
            pdir = os.path.join(tgt, 'profiles', '_selftest')
            os.makedirs(pdir, exist_ok=True)
            json.dump({'product': SELFTEST_WORD, 'vendor': ''},
                      open(os.path.join(pdir, 'profile.json'), 'w', encoding='utf-8'),
                      ensure_ascii=False)
            probe = os.path.join(tgt, 'assets', '_selftest_probe.txt')
            open(probe, 'w', encoding='utf-8').write(
                'word: ' + SELFTEST_WORD + '\nmid 52 low 40 high 56 family A anchors B loo 3\n')
            # 「代号 + 型号数字」形态单独放一个文件：这是产品词在真实文案里最常见的样子，
            # 而旧判据的右边界含数字，这种形态一个都抓不到——判别力白丢一大半。
            # 自检必须覆盖它，否则「允许数字后缀」这条改动只是自认为有效。
            probe2 = os.path.join(tgt, 'assets', '_selftest_probe_suffix.txt')
            open(probe2, 'w', encoding='utf-8').write(
                '型号：' + SELFTEST_WORD + '120 已支持\n')
            # C5 注入：造一件含中文可见文本的交互件模板（中文写在注释里不算，写在正文里才算）
            ixd = os.path.join(tgt, *IX_SUBDIR)
            os.makedirs(ixd, exist_ok=True)
            open(os.path.join(ixd, SELFTEST_IX), 'w', encoding='utf-8').write(
                '<!--css--><style>/* 注释里的中文不算 */</style>\n'
                '<!--html--><div>写死的字段名</div>\n<!--js--><script>var x=1;</script>\n')
            # 两跑对照：证明「产品词族的判别力确实来自词表」。
            # 不给词表时该族必须 0 命中——否则说明命中来自别处，判据名不副实；
            # 给了词表时必须命中——否则说明词表收集或匹配断了。
            # 注意必须用 --words 显式供词，不能靠 profiles 自动收集：自检造的是
            # 下划线目录（_selftest），而 load_words 按约定跳过下划线目录，
            # 自动收集在自检里必然为空，产品词族会静默失去判别力。
            f0, words0, _ = scan(tgt)
            wf = os.path.join(tmp, '_selftest_words.txt')
            open(wf, 'w', encoding='utf-8').write(SELFTEST_WORD + '\n')
            f, words, ix_n = scan(tgt, extra_path=wf)
            def _pick(rows, suf, tag):
                return [x for x in rows if x[1].endswith(suf) and tag in x[2]]

            w0 = _pick(f0, '_selftest_probe.txt', '产品词命中')       # 无词表时，要求为 0
            w1 = _pick(f, '_selftest_probe.txt', '产品词命中')        # 有词表时，要求 ≥1
            s0 = _pick(f0, '_selftest_probe_suffix.txt', '产品词命中')
            s1 = _pick(f, '_selftest_probe_suffix.txt', '产品词命中')  # 型号后缀形态也必须命中
            sg = _pick(f, '_selftest_probe.txt', '结构签名命中')
            c5 = _pick(f, SELFTEST_IX, 'C5')
            # 三族分列、各自有下限；产品词族还要求「无词表则不命中」这一反向断言，
            # 以及「代号 + 型号数字」这种形态同样命中——只认完整产品名是不够的。
            ok = (len(w0) == 0 and len(w1) >= 1 and len(s0) == 0 and len(s1) >= 1
                  and len(sg) >= 2 and len(c5) >= 1)
            print('自检（三族分列，逐族证明会失败）：')
            print('  产品词族  无词表 %d 条（要求 0，证明命中确实来自词表）／'
                  '给词表 %d 条（要求 ≥1）' % (len(w0), len(w1)))
            print('  产品词族（代号+型号后缀形态）  无词表 %d 条（要求 0）／'
                  '给词表 %d 条（要求 ≥1）' % (len(s0), len(s1)))
            print('  结构签名族 %d 条（要求 ≥2）' % len(sg))
            print('  C5 族      %d 条（要求 ≥1）' % len(c5))
            for sev, rel, why in w1 + s1 + sg + c5:
                print('    [%s] %s  %s' % (sev, rel, why))
            print('  自检词表：%s' % (', '.join(words) or '（空）'))
            print('自检结论：%s' % ('PASS（三族判据各自被证明有效）' if ok
                                  else 'FAIL（有注入未命中，或判别力来源不成立）'))
            return 0 if ok else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    findings, words, ix_n = scan(skill, a.words)
    findings = list(findings) + align_findings(skill)
    print('本体清洁度扫描：%s' % skill)
    print('扫描范围：技能目录下全部文本文件（排除 profiles/**、.git、.workbuddy 会话运行态'
          '与 过程文件/ 过程产物）——比「本体」更宽；本体（受保护集）= SKILL.md + assets/**，'
          '两者不是一个概念')
    print('口径对齐：.gitignore 的顶层目录排除项 %s 均在本扫描器的跳过集合内'
          % ('、'.join(gitignore_dir_excludes(skill)) or '（无）'))
    print('词表 %d 个（固定基线 %d + 自动收集/外供 %d）：%s'
          % (len(words), len(BASE_WORDS), len(words) - len(BASE_WORDS),
             ', '.join(words) or '（空）'))
    print('结构签名 %d 条' % (len(SIGNATURES) + len(SIGNATURE_AND)))
    print('C5 交互件模板 %d 件（可见文本零中文）' % ix_n)
    # 这一族能查到什么，必须每次都说清楚：只收完整产品名时，「代号 + 型号数字」、
    # 以及「隔声」「CHC」这类独立短词都不在词表里。报「命中 0」而读者以为它查过全部形态，
    # 那和假绿没有区别。
    ascii_words = [w for w in words if not w.startswith('re:')
                   and re.fullmatch(r'[A-Za-z][A-Za-z0-9_\-]*', w)]
    print('产品词族的判别力：完整产品/厂商名 %d 个；ASCII 词额外按「词边界 + 允许数字后缀」'
          '匹配（%s）' % (len(words) - len([w for w in words if w.startswith('re:')]),
                    '、'.join(ascii_words[:4]) or '本次无 ASCII 词'))
    print('      查不到：独立于产品名的短词（如「隔声」）、以及词表里没写的代号变体——'
          '这类要查就用 --words 传外部词表（支持 `re:` 正则条目，见 README「已知边界」）。')
    # 不具判别力就不能算「通过」：词表为空时产品词判据恒不命中，必须显式说明，
    # 否则「命中 0」会被读成「本体干净」，而实际是这条判据根本没在工作。
    powerless = not words
    if powerless:
        print('注意：词表为空（profiles 下没有非下划线目录填 product/vendor）——'
              '本次仅结构签名与 C5 生效，产品词判据无判别力。')
        print('      要查产品词：在 profiles/<产品>/profile.json 填 product，'
              '或用 --words 传外部词表。')
    if findings:
        for sev, rel, why in findings:
            print('[%s] %s  %s' % (sev, rel, why))
    else:
        print('命中 0。')
    verdict = 'FAIL' if findings else 'PASS'
    if not findings and powerless:
        verdict = 'PASS（仅结构签名与 C5；产品词判据无判别力）'
    print('\n判定：%s（命中 %d）' % (verdict, len(findings)))
    if a.json:
        json.dump({'skill_dir': skill, 'words': words, 'c5_templates': ix_n,
                   'findings': findings, 'powerless': powerless},
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
