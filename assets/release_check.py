#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布前闸门：把 CONTRIBUTING.md 里那几条散文清单变成会 FAIL 的检查。

用法：
  python assets/release_check.py [--skill-dir <技能目录>]

为什么单独成一个脚本而不是补进某个现成脚本：
  发布检查的对象是「包本身」（版本落了几处、该带的件在不在、有没有残留产物），
  与 check_demo（判成品）、audit_body（判本体文本）都不是同一层，塞进去只会让三者都变糊。

这几条不为难人，只为堵住已经发生过的那一类错：版本号同时落在 SKILL.md / manifest.json /
CHANGELOG 三处，而发布前清单里没有任何一条会去对它们——于是「SKILL.md 写着 1.2.0、
manifest 写着 1.3.0」这种状态能一路溜到发布，而技能平台读的恰恰是 SKILL.md 的 frontmatter。

退出码：0 = 全部通过；1 = 有 FAIL。SKIP 用于「这次不具备条件」的条目（例如不在 git 仓内）。
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 随库发布的示例配置。RC4（内容包齐全）与 RC5（会入库）共用这一份列表——
# 加示例时只在这里加，别在用到的地方各抄一遍。
EXAMPLE_PROFILES = ('_示例', '_示例-带图', '_示例-inline')
sys.path.insert(0, HERE)

FRONT_VERSION = re.compile(r'(?m)^version:\s*([0-9][^\s]*)\s*$')
CHANGELOG_TOP = re.compile(r'(?m)^##\s*v?([0-9][^\s]*)\s*[—-]')
BODY_JUNK = ('__pycache__', '_negtest', '.pytest_cache')
BODY_JUNK_EXT = ('.pyc',)


def read(p):
    return open(p, encoding='utf-8').read()


def _ignored(rel, cwd):
    """git check-ignore：0 = 被排除，1 = 不排除，其他/异常 = 判不了（返回 None）。"""
    try:
        r = subprocess.run(['git', 'check-ignore', '-q', '--', rel],
                           cwd=cwd, capture_output=True, timeout=30)
    except Exception:
        return None
    if r.returncode in (0, 1):
        return r.returncode == 0
    return None


# RC6 用：比对两处目录时要跳过的目录（与同步动作同一口径）
EXCLUDE_DIR = ('.git', '__pycache__', '.workbuddy', '过程文件')


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(65536), b''):
            h.update(b)
    return h.hexdigest()


def _rel_set(root):
    """{相对路径: sha256}，读不动的记成 None。"""
    s = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in EXCLUDE_DIR]
        for fn in fns:
            if fn.endswith('.pyc'):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace('\\', '/')
            try:
                s[rel] = _sha(p)
            except Exception:
                s[rel] = None
    return s


def _git_lag(src, run):
    """两边都是 git 仓时报「副本落后几个 commit」；判不了就返回空串（不冒充结论）。"""
    try:
        hs = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=src,
                            capture_output=True, text=True, timeout=30)
        hr = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=run,
                            capture_output=True, text=True, timeout=30)
        if hs.returncode or hr.returncode:
            return ''
        a, b = hs.stdout.strip(), hr.stdout.strip()
        if not a or not b or a == b:
            return ''
        cnt = subprocess.run(['git', 'rev-list', '--count', '%s..%s' % (b, a)], cwd=src,
                             capture_output=True, text=True, timeout=30)
        n = cnt.stdout.strip() if cnt.returncode == 0 else '?'
        return ('；副本 git 历史停在 %s（落后 %s 个 commit——那是副本自己的 git 记录，'
                '文件已逐字节一致，不影响被加载的内容）' % (b[:7], n))
    except Exception:
        return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skill-dir', default=os.path.dirname(HERE))
    ap.add_argument('--runtime-dir', default='',
                    help='宿主实际加载的运行态副本目录；缺省按 ~/.workbuddy/skills/<技能目录名> 探测')
    a = ap.parse_args()
    skill = os.path.abspath(a.skill_dir)
    ok, skip, fail = [], [], []

    def path(*parts):
        return os.path.join(skill, *parts)

    # ---- RC1 版本三处一致 ----
    versions = {}
    sk = path('SKILL.md')
    if os.path.isfile(sk):
        m = FRONT_VERSION.search(read(sk))
        versions['SKILL.md frontmatter'] = m.group(1) if m else None
    else:
        fail.append('RC1 缺 SKILL.md')
    mf = path('manifest.json')
    if os.path.isfile(mf):
        try:
            man = json.loads(read(mf))
        except ValueError as e:
            man = {}
            fail.append('RC1 manifest.json 不是合法 JSON：%s' % e)
        versions['manifest.json version'] = man.get('version')
        tag = (man.get('release_metadata') or {}).get('release_tag_recommendation')
        versions['manifest 建议 tag'] = tag.lstrip('v') if isinstance(tag, str) else None
    else:
        man = {}
        fail.append('RC1 缺 manifest.json')
    cl = path('CHANGELOG.md')
    if os.path.isfile(cl):
        m = CHANGELOG_TOP.search(read(cl))
        versions['CHANGELOG 顶部'] = m.group(1) if m else None
    else:
        fail.append('RC1 缺 CHANGELOG.md')

    known = {k: v for k, v in versions.items() if v}
    if len(known) < 2:
        fail.append('RC1 版本只读到 %d 处，无法比对（%s）' % (len(known), versions))
    elif len(set(known.values())) != 1:
        fail.append('RC1 版本号三处不一致：%s —— 技能平台读的是 SKILL.md 的 frontmatter'
                    % '；'.join('%s=%s' % (k, v) for k, v in sorted(known.items())))
    else:
        ok.append('RC1 版本号三处一致（v%s）：%s'
                  % (next(iter(known.values())), '、'.join(sorted(known))))

    # ---- RC2 发布的件都在 ----
    comps = man.get('factory_components') or []
    if not comps:
        skip.append('RC2 manifest 没登记 factory_components，本次未核')
    else:
        missing = [c for c in comps if not os.path.exists(path(c))]
        if missing:
            fail.append('RC2 manifest 登记了却不存在：%s' % '、'.join(missing))
        else:
            ok.append('RC2 factory_components %d 项全部存在' % len(comps))

    # ---- RC3 本体目录不残留运行期产物 ----
    junk = []
    for root, dirs, files in os.walk(path('assets')):
        dirs[:] = [d for d in dirs if d not in BODY_JUNK]
        junk += [os.path.join(root, f) for f in files if f.endswith(BODY_JUNK_EXT)]
    for name in BODY_JUNK:
        if os.path.exists(path(name)):
            junk.append(path(name))
    for name in ('_negtest', 'demo.html', 'demo2.html'):
        if os.path.exists(path(name)):
            junk.append(path(name))
    if junk:
        fail.append('RC3 仓内残留运行期产物：%s' % '、'.join(sorted(junk)[:6]))
    else:
        ok.append('RC3 无运行期残留（__pycache__ / _negtest / 临时成品）')

    # ---- RC4 仓内示例配置仍可跑通所依赖的件齐全 ----
    # 示例清单只此一处：RC4 与 RC5 都从它取。早先两处各抄一遍列表，加第三份示例时
    # 必然会漏改一边——那种「清单自己分裂成两份」正是本仓已经犯过的毛病。
    need_files = []
    for prof_rel in EXAMPLE_PROFILES:
        pj = path('profiles', prof_rel, 'profile.json')
        if not os.path.isfile(pj):
            skip.append('RC4 没有 profiles/%s，跳过' % prof_rel)
            continue
        try:
            prof = json.loads(read(pj))
        except ValueError as e:
            fail.append('RC4 profiles/%s/profile.json 不是合法 JSON：%s' % (prof_rel, e))
            continue
        d = os.path.join(path('profiles', prof_rel))
        for key, default in (('content', 'content.json'), ('sections', 'sections.html')):
            rel = prof.get(key, default)
            if not os.path.isfile(os.path.join(d, rel)):
                need_files.append('%s/%s' % (prof_rel, rel))
        inter = prof.get('interaction') or {}
        if inter.get('data') and not os.path.isfile(os.path.join(d, inter['data'])):
            need_files.append('%s/%s' % (prof_rel, inter['data']))
        for key, rel in (prof.get('assets') or {}).items():
            if rel and not os.path.isfile(os.path.join(d, rel)):
                need_files.append('%s/%s' % (prof_rel, rel))
    if need_files:
        fail.append('RC4 示例配置缺内容包：%s' % '、'.join(need_files))
    else:
        ok.append('RC4 %d 份示例配置的内容包齐全（干净克隆可直接跑）' % len(EXAMPLE_PROFILES))

    # ---- RC5 示例配置确实会入库 ----
    # RC4 只证明「文件在磁盘上」，干净克隆拿到的却是「git 认为该入库的那些」——两者不是一回事。
    # 第二份示例 `_示例-带图/` 就在这里翻过车：.gitignore 用 `profiles/*` 默认排除、
    # 放行规则只枚举了 `_模板` 与 `_示例` 两个名字，于是它被悄悄排除，而 RC4 照样报 PASS。
    # 有这一条，同类漂移会在发布前被拦下，而不是等别人 clone 下来才发现少一个示例。
    blocked, undecided = [], False
    for prof_rel in EXAMPLE_PROFILES:
        d = path('profiles', prof_rel)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), skill).replace('\\', '/')
                r = _ignored(rel, skill)
                if r is None:
                    undecided = True
                elif r:
                    blocked.append(rel)
    if undecided and not blocked:
        skip.append('RC5 不在 git 仓内或 git 不可用，入库可见性本次未核')
    elif blocked:
        fail.append('RC5 示例文件被 .gitignore 排除，干净克隆里不会有它：%s'
                    % '、'.join(sorted(blocked)[:6]))
    elif not undecided:
        ok.append('RC5 %d 份示例配置全部会被 git 跟踪（不被 .gitignore 排除）'
                  % len(EXAMPLE_PROFILES))

    # ---- RC6 源仓 ↔ 运行态副本一致 ----
    # 宿主真正加载的是运行态副本（~/.workbuddy/skills/<技能目录名>/），不是本仓工作树；
    # 这两处之间的搬运目前靠人记得。实测过一次：副本落后 5 个 commit、12 份里 11 份内容不同、
    # release_check.py 在副本里整份不存在——于是「源仓改好了」不等于「用户用上了」。
    # 副本找不到时必须 SKIP 并说明，不许静默放绿：看不见不等于一致。
    # 探测路径只算一处：SKIP 文案里报给人的路径，必须与实际找过的那处是同一处。
    # 早先这里在「探测」和「报错」两处各拼一遍——一处用 basename、一处留着 <本技能名>
    # 没替换，于是报错指的路根本不是刚才找过的路。同一事实两份来源迟早分叉，
    # 这个毛病本仓在别处已经付过学费（示例清单、文本口径、NEEDS_ARG）。
    guess = os.path.join(os.path.expanduser('~'), '.workbuddy', 'skills',
                         os.path.basename(skill))
    runtime = os.path.abspath(a.runtime_dir) if a.runtime_dir else ''
    if not runtime:
        runtime = guess if os.path.isdir(guess) else ''
    if not runtime or not os.path.isdir(runtime):
        skip.append('RC6 未找到运行态副本（找过 %s），本次未核——'
                    '被宿主加载的是副本，与源仓不一致就等于改动没生效'
                    % (runtime or guess))
    elif os.path.abspath(runtime) == os.path.abspath(skill):
        skip.append('RC6 本次就跑在运行态目录里，源仓与副本同一处，未核')
    else:
        A, B = _rel_set(skill), _rel_set(runtime)
        diffs = ['+%s（源仓有、副本没有）' % r for r in sorted(set(A) - set(B))]
        diffs += ['-%s（副本有、源仓没有）' % r for r in sorted(set(B) - set(A))]
        diffs += ['%s（两边内容不同）' % r for r in sorted(set(A) & set(B))
                  if A[r] is None or B[r] is None or A[r] != B[r]]
        if diffs:
            fail.append('RC6 运行态副本与源仓不一致，改动没搬到被加载的那一处（%d 处）：%s'
                        % (len(diffs), '；'.join(diffs[:6])))
        else:
            ok.append('RC6 运行态副本与源仓逐文件一致（%d 份）%s'
                      % (len(A), _git_lag(skill, runtime)))

    for line in ok:
        print('PASS  ' + line)
    for line in skip:
        print('SKIP  ' + line)
    for line in fail:
        print('FAIL  ' + line)
    print('\n发布闸门：%s（PASS %d / FAIL %d / SKIP %d）'
          % ('PASS' if not fail else 'FAIL', len(ok), len(fail), len(skip)))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
