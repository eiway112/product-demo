# `_示例/` — 仓内自带的最小可跑示例

**它是什么**：一份完整可跑的产品配置，用于两件事——

1. **当示范**：想知道「一份合格的配置长什么样」，看这里。字段含义见 `../_模板/README.md`。
2. **当「本体零改动」复检的输入**：`clone` 下来**不改任何东西**即可跑通全链路，所以能用来验证本体没被改坏
   （把下面这几条命令接进任何 CI 即可；本仓的 CI 见 `.github/workflows/ci.yml`——它已写入但从未在
   GitHub 上真正跑过，见根 `README.md` 的「已知边界」）。

**它不是**新建产品的起点——新建请复制 `../_模板/`，别复制这里（会把示例的文案与数据一并带过去）。

## 跑通它

在仓根执行：

```bash
python assets/build_demo.py --profile profiles/_示例/profile.json --out demo.html
python assets/check_demo.py demo.html --profile profiles/_示例/profile.json --img 0 \
  --expect pass=23,fail=0,skip=2
python assets/check_demo.py demo.html --profile profiles/_示例/profile.json --img 0 \
  --chrome "<chromium 路径>" --js-value IXRDY --expect pass=27,fail=0,skip=2
python assets/negative_test.py demo.html --profile profiles/_示例/profile.json --img 0
python assets/negative_test.py demo.html --profile profiles/_示例/profile.json --img 0 \
  --chrome "<chromium 路径>" --js-value IXRDY
python assets/check_demo.py --self-test
python assets/audit_body.py
python assets/audit_body.py --self-test
```

（`--img 0`：本示例刻意不配图，所以契约图数是 0。）

### 各步的预期输出

| 命令 | 预期 | 怎么看 |
|---|---|---|
| `build_demo` | 退出码 0，打印「出件：…（约 14000 字节，交互件 calculator，section 5 段）」 | 字节数不必逐字节对，`section 5 段` 和 `calculator` 必须对 |
| `check_demo`（离线） | `PASS 23 / FAIL 0 / SKIP 2` | 两条 SKIP：V2（本示例无图，无可判对象）＋整组浏览器判据（没给 `--chrome`） |
| `check_demo`（带 `--chrome --js-value IXRDY`） | `PASS 27 / FAIL 0 / SKIP 2` | 浏览器组 5 条（B5/V3/V5/V7/V8）里跑掉 4 条，只剩 V7 列 SKIP（没请求截图）。要连 V7 一起跑，再加 `--shot <任意 png 路径>`（跑完自行删除），那时是 `PASS 28 / FAIL 0 / SKIP 1`（剩下那条 SKIP 是无图的 V2） |
| `negative_test`（离线） | `通过 20 / 问题 0 / 跳过 6`，退出码 0 | 26 条用例里跳过 6 条：2 条本示例无图所致、4 条需 `--chrome`（含 V7 的空白截图注入） |
| `negative_test`（带 `--chrome --js-value IXRDY`） | `通过 24 / 问题 0 / 跳过 2`，退出码 0 | 剩下 2 条跳过即「无图」那两条；V7 的空白截图注入在这里真跑并必须被拦下 |
| `audit_body.py` | 退出码 0。判定行**分两种**：本机（`profiles/` 下有真实产品配置）是 `判定：PASS（命中 0）`；干净克隆里是 `判定：PASS（仅结构签名与 C5；产品词判据无判别力）` | 干净克隆里词表必然为空——这条判据会**明说自己没判别力**，而不是印一个裸 `PASS`。看到那句限定语是正常的，不是故障 |
| `audit_body.py --self-test` | 三族分列，各达标，`自检结论：PASS` | 产品词族会显示「无词表 0 条／给词表 1 条」 |

**关于 `--js-value IXRDY`**：这是交互件契约 C6 的取证锚点——模板在脚本末尾（`IX_init()` 之后）
往 `<html>` 上写 `data-ix-ready="IXRDY"`，属性值在源码里是拼接写法、不出现连续字面量。
于是「值出现在渲染后的 DOM、却不在源码里」这件事本身，就证明了**脚本真的执行到底**。
不给 `--js-value` 时 V3 会列 `SKIP`（而不是悄悄跳过）——它只是没被验证，不等于通过。

**关于那 2 条跳过**：`删除一张内联图`（期望 B2）与 `截断一张图的 base64`（期望 V2）
在本示例上会被报成 `SKIP`——因为本示例没有图，这两处注入**找不到注入点**。
这是刻意设计的三态：**「测不了」既不冒充通过，也不冒充失败**。跳过项会在汇总里
逐条列出，不会被总数掩盖。若换个有图的成品跑，这两条就会真的执行；而当
`--img` 明确要求有图、成品却没有时，它们会报 `FAIL`（那是成品缺陷，不是测不了）。

**关于 R1**：本示例的 `product` 是虚构的 `示例估算器`，所以元判据 R1 的词表只有
1 个词，判别力很弱（它在这一跑里只证明「机制在工作」，不证明「真产品也干净」）。
真要查产品词，得用真实产品的 profile 或 `--r1 "词1,词2"`。

**关于本体清洁度扫描的词表**：`audit_body.py` 的词表来自 `profiles/<产品>/profile.json`
的 `product` / `vendor`；而下划线开头的目录（`_模板` / `_示例`）按约定**不进词表**——
它们是基础设施，不是产品配置。于是：

- 在**本机仓**里（`profiles/` 下有真实产品配置），词表非空，产品词判据有判别力；
- 在**干净克隆**里（真实配置被版本控制排除），词表为空，该判据自动降级，并在判定行
  明说「无判别力」，剩下结构签名与 C5 两族继续工作。

这不是故障，是有意设计。**C5 用「可见文本零中文」而不是产品名词表，正是为了在没有
任何配置的克隆里也保住判别力**；而词表为空时不许印裸 `PASS`——那会让人把「没查」
读成「查过且干净」——必须把降级行为说出来。

## 它演示了什么形态

计算型（档位 → 数值：点选预设档位，看该档位的指标集），配档位对照器 `assets/interactions/calculator.html`。

产品的差异全在配置里：正文在 `sections.html`、数据在 `items.json`、品牌与文案在 `content.json`——
本体（`SKILL.md` + `assets/**`）一行都不必改。这正是「换产品本体零改动」这条验收所需的**可复现输入**：
没有它，那条验收只在维护者本机成立。

## 数值说明

`items.json` 里的数值全部是**演示用虚拟值**，不对应任何真实产品、项目或报价。

示例刻意不带 logo / hero 图（`profile.json` 的 `assets` 留空即不出图），以免往仓里塞二进制素材；
这也顺带验证了「可选素材真的可选」。
