# `_示例-inline/` — 第三份示例配置（交互件嵌在正文里）

**它为什么存在**：它只验证一件事——`interaction.position = "inline"`。

出件器里「交互件按 `sections.html` 中 `<!--INTERACTION-->` 标记的位置**原地插入**」这条分支，
此前在仓内**没有任何配置声明过**，属于「有代码、从未被走过」的分支：默认走的是 `front`
（把交互件提到所有分节之前）。一条从没被走过的分支，和一条不存在的分支，在验收上没区别。

**补了示例还不够**：判据 **I4** 会比对 profile 声明的位置与成品里交互件出现的实际次序——
声明 inline 却仍插在最前面，必 FAIL。这才让「换了个装配位置」这件事真的被机器守住。

**它不是**新建产品的起点——新建请复制 `../_模板/`。本目录内容沿用 `../_示例/`，
**唯一差异就是装配位置**：两份成品应当只差交互件落在哪里。

## 跑通它

```bash
python assets/build_demo.py --profile profiles/_示例-inline/profile.json --out demo3.html
python assets/check_demo.py demo3.html --profile profiles/_示例-inline/profile.json --img 0 \
  --expect pass=24,fail=0,skip=3
python assets/negative_test.py demo3.html --profile profiles/_示例-inline/profile.json --img 0
python assets/check_demo.py demo3.html --profile profiles/_示例-inline/profile.json --img 0 \
  --chrome "<chromium 路径>" --js-value IXRDY --expect pass=28,fail=0,skip=3
python assets/check_demo.py --self-test
python assets/audit_body.py
python assets/audit_body.py --self-test
```

（`--img 0`：与 `_示例/` 一样刻意不配图，所以契约图数是 0。）

### 预期输出

| 命令 | 预期 | 怎么看 |
|---|---|---|
| `build_demo` | 退出码 0，打印「出件：…（约 2.2 万字节，交互件 calculator，section 5 段）」 | 交互件仍是 calculator——本示例改的是位置，不是形态 |
| `check_demo`（离线） | `PASS 24 / FAIL 0 / SKIP 3` | 三条 SKIP：V2（无图）＋ V9（无关键数字区）＋ 浏览器组（未给 `--chrome`） |
| `check_demo`（带 `--chrome --js-value IXRDY`） | `PASS 28 / FAIL 0 / SKIP 3` | 与 `_示例/` 同：浏览器组 5 条跑掉 4 条，V7 需 `--shot` 才执行 |
| 再加 `--shot <png 路径>` | `PASS 29 / FAIL 0 / SKIP 2` | 剩下两条 SKIP 是 V2 与 V9 |
| `negative_test`（离线） | `通过 22 / 问题 0 / 跳过 7`，退出码 0 | 29 条用例：2 条无图、1 条无关键数字区、4 条需 `--chrome` |
| `negative_test`（带 `--chrome --js-value`） | `通过 26 / 问题 0 / 跳过 3`，退出码 0 | 剩 3 条跳过即无图 2 条 + V9 1 条 |

数字与 `../_示例/` **逐项相同**是预期的：两者的差别在装配位置，不在判据覆盖面。
若哪天这两份的数字开始分叉，先查是不是其中一份的 `position` 没生效——
这正是 I4 存在的意义。

## 它演示了什么形态

计算型（档位 → 数值），与 `_示例/` 同一个档位对照器 `assets/interactions/calculator.html`；
差别只在 `profile.json` 里声明 `interaction.position = "inline"`，并且 `sections.html` 里
把 `<!--INTERACTION-->` 标记放在叙事中间（先讲清毛病，再给可玩的东西）。

## 数值说明

`items.json` 里的数值全部是**演示用虚拟值**，沿用 `../_示例/`，不对应任何真实产品、项目或报价。
