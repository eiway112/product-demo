# product-demo

给任意产品/项目生成**单文件、离线自包含、可交互**的对外演示网页——双击即开、可直接发微信、零外部依赖。

它不走「让模型随便写个落地页」那条路，而是一条**带机器判据的四道闸门**：
出件 → 核验 → 负向测试 → 本体清洁度。每一步都对产出物提可执行断言，
而且判据被改错时必须能被证明已经失效（靠负向注入，不靠人眼复查）。

> **术语**：这里的「四道闸门」是**机器判什么**；`SKILL.md` 的「四步流水线」是**人按什么顺序做事**
> （意图锚定 / 素材准备 / 视觉出件 / 核验落盘）。两者同叫「四步」但不是一个东西——
> 说「第 3 步」时请带上哪一套。

## 它解决什么

让模型直接写演示页，会稳定地翻三类车：

1. **写完不知道好不好**——没有判据，「看起来不错」当验收；
2. **叙事缺件**——只剩功能罗列，没有痛点、没有实证、没有边界，读者判断不了能不能用；
3. **换产品就改造型**——同一条管线换个产品，骨架里还焊着上一个产品的字段结构。

对应解法分别是：三层机器判据、叙事五要件、本体与配置分离。

## 三层结构

| 层 | 位置 | 是否随产品变 |
|---|---|---|
| 本体 | `SKILL.md` + `assets/**` | 不变。**任何具体产品名都不得出现** |
| 交互件模板库 | `assets/interactions/` | 按**交互形态**选，不按产品选 |
| 产品配置 | `profiles/<产品>/` | 每个产品一份；所有可变内容都在这里 |

新增产品**只加 `profiles/<产品>/`，本体一行不改**。判据：

```bash
git diff --stat -- SKILL.md assets/     # 应为 0 行
```

本体的清洁度不靠自觉，靠 `assets/audit_body.py` 扫描——它查三族：

1. **产品词**——词表自动从 `profiles/*/profile.json` 收集，本体自身不写死任何产品名；
2. **产品专属字段结构组合**——只查产品名是不够的：一个产品名都不出现，结构照样可能被污染；
3. **交互件模板可见文本零中文（C5）**——字段标签必须来自数据，不来自模板。

**这三族的判别力不同，别混为一谈**：第 1 族依赖本地 `profiles/` 收集到的词表，
所以在一份不含产品配置的干净克隆里必然为空、该族退化（脚本会明说"无判别力"，不印裸 PASS）；
第 2、3 族不依赖任何配置，到哪儿都有判别力。要查具体产品的词，用真实 profile 或 `--words` 传词表。

## 四道机器闸门

```bash
# 1) 出件
python assets/build_demo.py --profile profiles/<产品>/profile.json --out demo.html

# 2) 核验（离线判据）。--expect 把文档里的数字变成机器断言，交付与 CI 必须带上
#    · --img N 是契约不是提示：成品里应当正好有 N 张内联图，多一张少一张都 FAIL（无图件写 0）
#    · 下面这串数字是仓内 `_示例` 的实测值，换成别的产品要重跑一次再填，不要照抄
python assets/check_demo.py demo.html --profile profiles/<产品>/profile.json --img 2 \
  --expect pass=24,fail=0,skip=3

# 2b) 再跑一遍浏览器判据（无 console 报错、脚本真的执行了、没有横向溢出、点了有反应）
#     --js-value IXRDY 是模板契约 C6 的取证锚点；不给它，JS 执行那条判据只会列 SKIP
python assets/check_demo.py demo.html --profile profiles/<产品>/profile.json --img 2 \
  --chrome "/path/to/chrome.exe" --js-value IXRDY --expect pass=28,fail=0,skip=3

# 3) 负向测试：每条判据注入一处故障，断言必须被拦下；末行还判「注入覆盖率」
python assets/negative_test.py demo.html --profile profiles/<产品>/profile.json --img 2
# 3b) 也要带 --chrome 再跑一遍（离线与浏览器路径落在核验器不同返回分支）
python assets/negative_test.py demo.html --profile profiles/<产品>/profile.json --img 2 \
  --chrome "/path/to/chrome.exe" --js-value IXRDY

# 3c) 判据里的纯函数断言（如 V7 的像素校验）靠单测证明会失败
python assets/check_demo.py --self-test

# 4) 本体清洁度
python assets/audit_body.py
python assets/audit_body.py --self-test
```

**为什么要带 `--expect`**：浏览器那组判据在 `--chrome` 路径不可用时**全部列 SKIP 且退出码仍为 0**。
CI 里 `$(command -v google-chrome)` 返回空串就是这种情形——看起来全绿，实际一条浏览器判据都没跑。
断言期望条数是唯一能把它堵住的办法。

辅助脚本：

- `assets/extract_assets.py --html <页> --out-dir <目录>`——把既有单页 HTML 里的内联图与数据抽成产品配置素材；
- `assets/measure_density.py <html>...`——量化对照（标题层级、正文中文字数、唯一数值数）；
  它同时是**文本口径与词条匹配的单一事实来源**（`check_demo` / `audit_body` 都从它取实现）；
- `assets/release_check.py`——发布闸门 RC1–RC6：版本三处一致、该带的件在不在、
  有无运行期残留、示例内容包是否齐全、**示例会不会真的被 git 入库**、
  **源仓与宿主实际加载的运行态副本是不是逐文件一致**（只改源仓没同步＝改动没生效）。

`check_demo.py` 支持 `SKIP` 与 `PASS` 分列：因缺参数（未给 `--chrome` / `--js-value` / `--shot`）
而未执行的判据单列 SKIP，并在汇总行**逐条列出**，**不计入通过**——跳过的判据不算已经查过。
每条登记过的判据都必须出结论行（元判据 **U1 出席检查**），「既不 PASS 也不 SKIP」一律判 FAIL。

## 判据

### 结构层（B / V）

单文件、自包含、外链为 0、标签配对且**不嵌套**、无横向溢出、无 console 报错，
以及**脚本确实执行过**——后者靠模板按契约 C6 写入的 `data-ix-ready` 锚点取证：
只有脚本真跑到底，DOM 上才会出现那个属性。
其中「标签不嵌套」是踩出来的：交互件模板自带 `<style>`/`<script>` 包装时，若出件器不剥掉这一层，
嵌进骨架的脚本容器就会形成嵌套，浏览器在第一个 `</script>` 处截断，整块脚本一行都不执行——
页面打得开、看着正常，点了没反应。

「外链为 0」同时扫 **HTML 属性与 CSS 层**：`url()` / `@import` / `srcset` 一并判。
只扫 `src`/`href` 属性时，一条 `@import url("//evil.example.com/a.css")` 就能让成品在断网环境
下一片空白，而判据仍报绿——「零外部依赖」这条此前只在 HTML 属性层成立。

### 叙事层（N1–N5）

五要件：**痛点 / 方法 / 实证 / 差异 / 边界**。
每件都要落到 `data-role` 上（`pain` / `method` / `evidence` / `diff` / `boundary`），
缺哪件就必须显式声明一段 `data-role="gap"`。空壳（只有小标题、没有正文）不算数；
缺件时交互件数必须为 0，不许硬凑。

### 交互层（I1–I3）与交互往返（V8）

交互件硬契约：

- 主输出容器 `id="ix-body"`，初始态为 `—`；
- `IX_init()` 有定义，且在首次渲染路径上被调用一次（判之前先剥 JS 注释，
  行注释与块注释都剥——被注释掉的调用长得和真调用一样）；
- 数据项 ≥2，每项字段齐全。

**V8 · 交互往返**（需 `--chrome`）：派发一次真实点击 → 回读 DOM → 与数据源的第 k 项逐项比对。
它是唯一一条问「点了有没有反应」的判据。少了它，下面这些故障在所有静态判据下都是全绿的：
卡片索引错位（点第 2 张渲染第 1 张）、某个分支只在特定 item 上抛错、事件绑定失效、面板只更新一半。
V3 只证明初始化跑通了，不等于交互可用。

完整契约 C1–C7 写在 `assets/interaction_patterns.md`：**I1–I3 是 C1–C4 的机器判据**，
C5（模板可见文本零中文）与 C6（模板必须提供 V3 取证锚点 `data-ix-ready`）作用在交互件
**模板**上、属本体清洁度：C5 由 `audit_body.py` 守，C6 在调用时用 `--js-value IXRDY` 验证——
只跑 `check_demo.py` 会漏掉 C5，不给 `--js-value` 则连 C6 也验不到。
V8 对应新契约 **C7**（可按索引点击的卡片与主标题容器）。

### 这些判据不能证明什么

判据能证明：结构自包含（HTML 属性与 CSS 层都不外链）/ 五要件在场且非空壳 /
内联数据与数据源**逐字符一致** / 初始态为 `—` / 锚点存在（脚本跑到底）/
**点击后渲染结果与数据源的第 k 项一致** / 无 console 报错 / 无横向溢出 /
截图是合法 PNG 且画面非空白。

判据**不能**证明：

- **数值本身是否真实**——它只比对「成品里的数 == 数据源里的数」，
  数据源里的数是谁量出来的、量对了没有，判据管不着；
- **口径标注是否正确**——「估算」与「实测」有没有标错，属 `profiles/<产品>/` 的纪律
  （`SECURITY.md` 已把这份责任划给配置层）；
- **叙事与产品事实是否一致**——一句话主张是不是真的，机器判不了；
- **版式好不好看、读起来顺不顺**——密度阈值是经验值，只拦退化，不保证好看；
- **在 Chromium 之外表现如何**——非 Chromium 内核未实测。

所以「带机器判据」不等于「内容已被机器验证过」。判据守的是**结构与一致性**，
守不了**事实与口径**。

## 交互形态四分类

按「这个产品能演示什么」定，不按行业定：

| 形态 | 判据 | 交互件 | 本仓模板 |
|---|---|---|---|
| 计算型 | 档位 → 数值 | 档位对照器 | `calculator.html` ✅ |
| 能力型 | 问题进 → 样例输出出 | 样例演示器 | `catalog.html` ✅ |
| 规格型 | 选项组合受约束 | 配置器 | 未建 |
| 流程型 | 步骤推进 → 状态变化 | 流程沙盘 | 未建 |

**✅ 的口径要说清**（否则它就是个没有依据的符号）：

- `calculator.html` —— 由仓内 `profiles/_示例/` 端到端跑通，**任何人都能复现**；
- `catalog.html` —— 由仓内 `profiles/_示例-带图/` 端到端跑通（第二份随库入库的示例，
  带两张极小的 PNG），**任何人都能复现**。此前它只在真实产品上跑过、那份配置不入库，
  所以 ✅ 只有维护者能核——这一处已补齐。

四问全否 → **不配交互件**，改在正文里放 `data-role="gap"` 说明缺什么。
硬凑一个空交互件比没有更糟。另两类的规范写在 `assets/interaction_patterns.md`，
本仓如实标注未建——不造未验证资产。

## 快速开始

**先跑仓内自带的示例**，确认环境没问题（不必先建自己的配置——`profiles/_示例/` 随库入库，全虚构值）：

```bash
git clone <this-repo> && cd product-demo

# 1) 出件
python assets/build_demo.py --profile profiles/_示例/profile.json --out demo.html

# 2) 核验（结构 / 叙事 / 交互三层离线判据）
python assets/check_demo.py demo.html --profile profiles/_示例/profile.json --img 0 \
  --expect pass=24,fail=0,skip=3

# 3) 负向测试：每条判据注入一处故障，断言必须被拦下
python assets/negative_test.py demo.html --profile profiles/_示例/profile.json --img 0

# 4) 本体清洁度
python assets/audit_body.py
```

（`--img 0`：该示例刻意不配图，所以契约图数是 0。每步的预期输出写在 `profiles/_示例/README.md`。）

**跑通了再照 `_模板/` 建自己的产品**：

```bash
cp -r profiles/_模板 profiles/我的产品
# 填 profiles/我的产品/ 下的 profile.json / content.json / sections.html / items.json
# 字段含义见 profiles/_模板/README.md
python assets/build_demo.py --profile profiles/我的产品/profile.json --out my.html
```

本仓自带三份示例：它们不只是"演示"，还是干净克隆里**唯一存在的完整配置**，
所以也是「本体零改动」复检的基线，以及 CI 的现成输入
（`_示例/` 不配图配计算型；`_示例-带图/` 配两张图与能力型，补上 B2/V2 与 catalog 的可复现性；
`_示例-inline/` 声明交互件嵌在正文中间，让出件器的 inline 分支也有可跑输入）。
每份示例的 `README.md` 都写了跑通步骤与逐步预期数字。
CI 配置见 `.github/workflows/ci.yml`——**它从未在 GitHub 上真正跑过**，见「已知边界」。

运行时只需要 Python 标准库（无任何第三方依赖）。只有浏览器判据需要本机有 Chrome/Chromium，
不给就单列 SKIP——跳过的判据不算已经查过。

## 目录结构

```
SKILL.md                        技能入口（身份、流程、判据索引、已知坑）
README.md                       本文件
LICENSE                         MIT
CHANGELOG.md                    变更记录
CONTRIBUTING.md                 参与与维护约定 + 提交前 / 发布前检查清单
SECURITY.md                     安全策略（含文件系统行为）
manifest.json                   发布元数据（版本、兼容性证据、以及缺哪些证据）
.gitattributes                  钉住 LF——行尾漂移会让「逐字节回读」变成假绿
.gitignore                      默认排除 profiles/*，只放行下划线开头的基础设施目录
.github/workflows/ci.yml        CI（未实跑过，见「已知边界」）
assets/
  template_skeleton.html        版式层骨架（品牌占位符 + 一个交互件插槽）
  interactions/
    calculator.html             交互件模板：档位对照器（计算型）
    catalog.html                交互件模板：样例演示器（能力型）
  build_demo.py                 出件器（骨架 + 产品配置 + 交互件模板 → 单文件 HTML）
  check_demo.py                 正向核验器（结构 / 叙事 / 交互 / 行为判据 + U1/U2/D 元判据 + 单测）
  negative_test.py              负向测试（每条判据注入故障，且判注入覆盖率）
  audit_body.py                 本体清洁度扫描（产品词 + 结构签名 + C5 零中文）
  extract_assets.py             素材提取器（既有单页 HTML → 产品配置素材）
  measure_density.py            量化对照 + 文本口径与词条匹配的单一事实来源
  release_check.py              发布闸门（版本三处一致 / 件齐 / 无残留 / 示例会入库）
  interaction_patterns.md       交互形态分类表 + 判据阈值与依据
profiles/
  _模板/                         新建产品配置的起点（基础设施，随库入库）
    README.md                   新建子流程 + 字段契约
    profile.json                字段骨架（照它填）
  _示例/                         最小可复现闭环（计算型，不配图；全虚构值）
    README.md                   跑通步骤 + 每步的预期输出
    profile.json                示例接线（assets 留空 → 不出图）
    content.json                页头页脚文案
    sections.html               叙事五要件正文
    items.json                  档位对照器数据源
  _示例-带图/                    第二份示例（能力型，带两张极小 PNG）
    README.md                   为什么要有第二份 + 预期输出
    profile.json / content.json / sections.html / items.json / logo.png / hero.png
  _示例-inline/                  第三份示例（交互件嵌在正文里，验证 inline 装配位置）
    README.md                   为什么要有第三份 + 预期输出
    profile.json / content.json / sections.html / items.json
```

## 已知边界

- **CI 配置已写入，但从未在 GitHub 上跑过**：`.github/workflows/ci.yml` 覆盖
  Linux / Windows / macOS × Python 3.9 / 3.13，输入用三份随库示例（干净克隆可直接跑），
  每一步都带 `--expect` 断言期望条数。**首次推送后请核对运行结果**——
  「配置已提交」不等于「已经验证」，这条区别正是本仓的判据在别处反复强调的。
  浏览器判据只在 Linux 上跑（runner 预装 Chrome）；其他平台那组列 SKIP，
  但期望条数是按平台分别断言的，所以「全列 SKIP 也算过」在那里不成立。
- **规格型 / 流程型交互件模板未建**，需要这两类的产品走 gap 处置（见交互形态表）。
- **浏览器判据需 Chromium 系**：其他内核的布局未实测。
- **密度阈值是经验值，不是标准**：取值与依据写在 `check_demo.py` 顶部的判据参数区，
  改动需与 `assets/interaction_patterns.md`、`SKILL.md` 同步——三处不同步会让阈值失去来源。
- **产品词判据只对「词表里有的词」有判别力**：词表来自 `profiles/*/profile.json` 的
  product/vendor（或 `--words` 外供）。ASCII 词按「词边界 + 允许数字后缀」匹配，
  所以「代号 + 型号数字」抓得到；但**独立于产品名的短词、以及词表里没写的代号变体不在覆盖内**。
  本仓刻意**不**随库配一份词表——那会把产品名写回本体，扫描器自己就成了最后一处产品名。
  要查这类词：`--words <仓外词表文件>`，支持 `re:<正则>` 条目。
- **`profiles/` 默认不入库**：产品配置常含未公开资产，本仓 `.gitignore` 采用
  「默认排除 `profiles/*`、按**模式**放行下划线开头的基础设施目录（`!profiles/_*/`）」——
  目前随库的有 4 个：`_模板/` 与三份示例。**放行规则刻意不枚举目录名**：按名字枚举过一次，
  新增的第二份示例就被 `profiles/*` 悄悄排除，本机一切正常、干净克隆却少了它。
  下划线前缀就是这个约定的标记：**带下划线＝基础设施，随库入库；
  不带＝产品配置，自动排除**。
  由此产生一个明确代价：**使用者自己的产品配置没有本仓的版本兜底**，需自行纳管。
- **只有本体与模板库做过跨产品验证**：本仓的通用性来自「新增产品时本体改动为 0」这条判据。
  在维护者本机已用不止一个真实产品跑通，但那些配置含商业资产、不入库——**外部读者可核的
  是随库的三份示例**（`_示例/` 计算型无图、`_示例-带图/` 能力型带图、`_示例-inline/` 交互件嵌正文）。
  判据本身只对已出现过的失败形态负责，新形态可能暴露新缺口。
- **判据守不了事实与口径**：见上文「这些判据不能证明什么」。

## 开发约定

- **改判据必须同时补负向注入用例**——判据写对了不等于写有效了；
  现在这条由负向测试的**覆盖率判据**机器守：本次参数下跑得到却没用例的判据会被点名 FAIL；
- **补注入时要换形态，别只补同一种**：判据与注入共用同一个盲区时，负向测试只能证明它们一起错在哪
  （`IX_init` 的行注释版与块注释版就是这种情形，两条都要留）；
- **负向测试要带 `--chrome` 再跑一遍**：离线路径与浏览器路径落在核验器不同的返回分支上，
  只跑离线会漏掉浏览器侧的全部改动；
- **嵌在浏览器流程里的断言另走单测**：`check_demo.py --self-test`
  （注入动不了它——比如 V7 判的是 Chrome 产出 PNG 的二进制）；
- 提交前跑：`audit_body.py`（本体 0 命中）+ 上面第 2、2b、3、3c 步。
- 完整的**提交前清单**与**发布前检查**见 `CONTRIBUTING.md`；每一步的预期数字见
  `profiles/_示例/README.md`、`profiles/_示例-带图/README.md`、`profiles/_示例-inline/README.md`
  ——对不上时改文档，别改实测。

## License

MIT
