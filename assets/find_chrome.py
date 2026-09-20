#!/usr/bin/env python3
"""跨平台定位 Chrome/Chromium —— 本仓浏览器判据的唯一定位入口。

为什么这件事值得单独一个文件，而不是在 ci.yml 里写「Linux 用 command -v、
Windows 用 Test-Path」两套 shell 分支：

① **能本地实测**。平台差异只存在于下面这张候选表里，本机跑一次 `--list` 就知道
   表对不对；shell 分支只能等 CI 告诉你，而这一等就是一次失败的推送。
② **不信 shell 的编码**。写 $GITHUB_ENV 必须 UTF-8 无 BOM：PowerShell 5.1 的
   Out-File / Add-Content 默认带 BOM，键名会变成 "\ufeffCHROME" —— 变量静默不存在，
   浏览器判据整组 SKIP。这类编码细节本仓已经翻过一次车（v1.8.2 的 cp1252），
   不再交给 shell 碰运气。
③ **两条腿共用一段逻辑**。Linux 与 Windows 走的是同一个函数、同一张表，
   不存在「两条腿的探测条件不一样」这种只在 CI 上才看得见的偏差。

退出码：找到 0；找不到 1，并打印 ::error::。
**找不到必须响亮失败** —— 静默跳过正是本仓反复标记的假绿形态：判据一行不出，
退出码还是 0，只有 --expect 的条数能把它顶回来，不如在这一步就断掉。
"""
import argparse
import os
import shutil
import sys

# 候选表：按平台列「官方安装器的默认落点」。顺序即优先级。
# 依据：actions/runner-images 的 Windows2025 / Ubuntu / macOS 镜像清单确认三者均预装
# Google Chrome，但清单只给版本不给路径；所以这里枚举平台默认位置 ——
# 枚举表可以被本地实测证伪，猜单个路径不能。
CANDIDATES = {
    'win32': [
        r'%ProgramFiles%\Google\Chrome\Application\chrome.exe',
        r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe',
        r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe',
    ],
    'darwin': [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome',
    ],
    'linux': [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/opt/google/chrome/chrome',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
    ],
}

# PATH 兜底：Linux 上最可靠的一路（发行版把可执行名放这儿，位置可能变）
PATH_NAMES = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']


def platform_key():
    if os.name == 'nt':
        return 'win32'
    return 'darwin' if sys.platform == 'darwin' else 'linux'


def candidates():
    """本平台的候选路径（已展开变量与 ~），保持优先级顺序。"""
    out = []
    for p in CANDIDATES[platform_key()]:
        # expandvars 在 Windows 上认 %VAR%，在 POSIX 上认 $VAR —— 各平台各取所需
        out.append(os.path.expanduser(os.path.expandvars(p)))
    return out


def find(paths=None, names=None):
    """在候选里找第一个存在的文件；找不到再按名字查 PATH；都没有返回 None。

    paths / names 可注入 —— 自检靠这个把「探测逻辑」与「本机恰好装了 Chrome」解耦：
    注入一条确定存在的路径必须命中，注入一条确定不存在的必须不命中。
    不注入就只能在本机测「找到了」这半边，测不了「找不到时会拒绝」那半边。
    """
    for p in (candidates() if paths is None else paths):
        if os.path.isfile(p):
            return p
    for n in (PATH_NAMES if names is None else names):
        w = shutil.which(n)
        if w:
            return w
    return None


def self_test():
    """断言探测逻辑本身，而不是「这台机器装了 Chrome」。"""
    bad = []
    me = sys.executable or ''
    if not me or not os.path.isfile(me):
        bad.append('自检前提不成立：sys.executable 不是文件（%r）' % me)
    else:
        if find(paths=[me], names=[]) != me:
            bad.append('注入一条存在的路径未命中：%r' % me)
        if find(paths=['/definitely/not/here/chrome'], names=[]) is not None:
            bad.append('注入一条不存在的路径却命中了（find 退化成永远返回第一条）')
    if find(paths=[], names=['definitely-not-a-real-program-xyz']) is not None:
        bad.append('PATH 兜底对不存在的程序名返回了值')
    # 本平台候选必须都是绝对路径 —— 相对路径会按 CWD 解析，正是 v1.8.2 那个 --shot 坑的同源
    for p in candidates():
        if not os.path.isabs(p):
            bad.append('本平台候选不是绝对路径：%s' % p)
    if bad:
        for b in bad:
            print('FAIL ' + b)
        return 1
    print('PASS find_chrome 自检：%d 张平台候选表；注入命中/不命中/PATH 兜底 各 1 例'
          % len(CANDIDATES))
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--write-env', action='store_true',
                    help='把 CHROME=<路径> 追加到 $GITHUB_ENV（CI 用；UTF-8 无 BOM）')
    ap.add_argument('--list', action='store_true', help='打印本平台候选表与命中情况')
    ap.add_argument('--self-test', action='store_true', help='自检探测逻辑（不依赖本机装没装）')
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    if a.list:
        hit = find()
        for p in candidates():
            print('%s  %s' % ('OK ' if os.path.isfile(p) else '-- ', p))
        print('PATH 兜底：%s' % '、'.join(PATH_NAMES))
        print('命中：%s' % (hit or '（无）'))
        return 0 if hit else 1

    p = find()
    if not p:
        print('::error::未找到 Chrome/Chromium —— 浏览器判据无法执行', file=sys.stderr)
        print('已尝试的候选路径：', file=sys.stderr)
        for q in candidates():
            print('  - %s' % q, file=sys.stderr)
        print('  - PATH: %s' % '、'.join(PATH_NAMES), file=sys.stderr)
        print('这里不允许静默跳过：整组 SKIP 会让 --expect 的条数失效（本仓的假绿形态）。',
              file=sys.stderr)
        return 1

    if a.write_env:
        # encoding='utf-8' 写出的是无 BOM 的 UTF-8 —— 与 PowerShell 的 Out-File 不同，
        # 后者在 5.1 下带 BOM，会把键名变成 "\ufeffCHROME"（见文件头 ②）。
        fen = os.environ.get('GITHUB_ENV')
        if not fen:
            print('::error::--write-env 需要 GITHUB_ENV 环境变量（该参数只用于 CI）',
                  file=sys.stderr)
            return 1
        with open(fen, 'a', encoding='utf-8', newline='\n') as f:
            f.write('CHROME=%s\n' % p)
        print('CHROME=%s（已写入 $GITHUB_ENV）' % p)
    else:
        print(p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
