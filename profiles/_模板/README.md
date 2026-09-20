# 新建产品配置子流程

> 触发：需求卡片里「配置来源」= 新建。**禁止沿用别的产品配置**（串味是最常见的翻车）。
> 本目录是新建的起点：**只含 `profile.json` 字段骨架 + 本说明**；其余内容包
> （`content.json` / `sections.html` / `items.json` / 口径与事实文件）按下面的契约自建。
> 产品配置一律落在 `profiles/<产品>/`，不得落进 `assets/`——
> `assets/` 属本体，任何产品名与产品素材进去就是污染，本体清洁度扫描会直接判失败。

## 目录结构（`profiles/<产品>/`）

```
profile.json      素材接线、落点、交互件类型声明           ← 技术接线（从本目录拷）
content.json      页头页脚文案、**品牌色**、交互件章节标题与标签、可选的关键数字 `stats` ← 叙事文本
sections.html     正文各段（每段必须带 data-role）          ← 叙事骨架
items.json        交互件数据源                              ← 数据
口径红线.md        哪些数值不许越界、必须标什么              ← 命名可自定，职责是「不许越的线」
事实数据.md        可引用的事实与出处（只放指针，不放整库）   ← 命名可自定
<图片素材>         降采样后的 logo / hero
```

> 后两类文件的**文件名可自定**（例如叫「锚点引用」「事实与口径」），判据不查名字，
> 只要求内容职责清楚。硬要求只有一条：**只放指针，不放整库数据**。

## 四步

1. **建目录**：复制本目录到 `profiles/<产品>/`（先得到 `profile.json`），
   再按上面的结构逐个补齐其余内容包。
   开工前先跑一遍 `profiles/_示例/`——示例是唯一随仓入库的产品配置，专门当
   「本机工具链通不通」的标尺；示例都跑不过，就还没到写自己配置的时候。
2. **问三件事**（缺什么问什么，不批量追问）：
   - 品牌色与字体从哪来（VI / 既有官网 / 既有软件界面）——**必须有出处，禁止现场臆造**；
   - 有没有不能越的口径红线（数值边界、必须标注的免责声明、不可换算的量）；
   - 可引用的事实数据在哪（文件 / 数据库 / 报告编号），**只放指针不放整库**。
3. **定交互形态**：按 `assets/interaction_patterns.md` 的四问定类型——
   有没有数（计算型）→ 有没有成型输出（能力型）→ 是不是可配组合（规格型）→ 是不是有序过程（流程型）。
   四问全否 → **不配交互件**，改在 `sections.html` 里放 `data-role="gap"` 段显式说明。
4. **建素材目录**：图片降采样后放**本项目目录**，`assets_dir` **留空即可**（留空＝素材就在本目录，
   见 `../_示例-带图/`）。**不要指向别的项目的资源目录**——那份目录被改名、迁移或重装换掉时，
   成品里的图会静默变化，而出件器唯一能做的只是打印一行「素材取自 profile 目录之外」的提示。

## `profile.json` 必填字段

**这张表按「有没有脚本真的读它」分成两组。** 混在一张「必填字段」表里会让
`delivery_dir` 这类只写给人类看的字段看起来像「填了就生效」——它就是这么被误读的。

### 机器消费（填错会被判据拦下）

| 字段 | 用途 | 消费点 |
|---|---|---|
| `product` / `vendor` | **只做两件事**：进本体清洁度扫描的词表（`audit_body.py` 里收集产品词的那一步），以及进元判据 R1 的词表（`check_demo.py` 的 R1 段）。**它们不进页头页脚**——页头取 `content.json` 的 `product_name`，页脚取 `content.json` 的 `footer_note` | `audit_body.py` / `check_demo.py` |
| `content` / `sections` | 指向 `content.json` 与 `sections.html`（相对本目录） | `build_demo.py` |
| `interaction.pattern` | 交互件类型：`calculator` / `catalog`（另两类模板未建，见分类表） | `build_demo.py` |
| `interaction.data` | 交互件数据源（相对本目录） | `build_demo.py` |
| `interaction.role` | 该件落在哪个叙事位（通常是 `evidence`） | `build_demo.py` |
| `interaction.position` | 交互件装配位置：`front`（默认）＝提到所有分节之前，叙事「先玩后读」；`inline`＝按 `sections.html` 里 `<!--INTERACTION-->` 标记的原位插入。**front 模式下标记仍必须存在**（出件器要靠它确认装配点已声明） | `build_demo.py` |
| `assets_dir` + `assets.*` | 素材路径指针（不在本体目录里放产品大文件）。`assets.logo` / `assets.hero` **留空即整块不出图**，见下节 | `build_demo.py` |
| `footer_note` | 页脚声明的**兜底值**：`content.json` 写了 `footer_note` 就以那边为准（见 `build_demo.py` 组装配方映射时取页脚兜底值那段）。口径红线要求的免责文字两边都要能落地，别只写一边 | `build_demo.py` |
| （品牌色**不**在这里） | 品牌色取自 **`content.json` 的 `brand`**。在 `profile.json` 里写 `brand` 不生效，出件器会打印提示——配色只留一个事实来源，避免两处打架 | `build_demo.py`（提示） |

### 仅约定（当前无任何脚本读取，填了不会生效）

| 字段 | 现状 |
|---|---|
| `delivery_dir` | 成品落点的**人类备注**，全仓脚本零引用。真要验落盘，用 `check_demo.py --deliver <成品文件路径>`——注意它要的是**文件**不是目录，所以这个字段没法直接喂给它 |
| `audience_default` / `form_default` | 纯约定，零引用。留给填写者记「这份件默认给谁看、默认什么形态」 |

**新增字段的规矩**：往 `profile.json` 加字段时，必须同时写明消费它的脚本与位置
（写**符号名或函数名**，不要写行号——行号会漂，第三方评审报告点名 `check_demo.py:1096—1105`
时它已经漂到 1110—1122，指认方自己也会漂）；
写不出来就一律放进「仅约定」这一组，并注明「填了不生效」。
否则字段表会再次漂成「看起来都生效」——那正是这一节被拆开的原因。

**这条规矩为什么不用脚本守**：最直觉的做法是「字段名在 `assets/*.py` 里 grep 命中 ≥1 即算有消费点」，
但它给的是**假绿**——`version`、`data`、`role` 这类名字在代码里到处都是，命中不等于被读，
而真正零消费的字段也能靠同名词蒙混过关。**宁可让规矩停在人工执行，也不要装一条会报绿的假判据**：
假绿比没有判据更危险，因为它会让人停止怀疑。

## 可选素材：没有图和有图都能出件

骨架把 logo 与 hero 包在成对的标记里：

```
<!--ASSET:logo--> … <img src="data:image/png;base64,__LOGO_B64__" …> … <!--/ASSET:logo-->
<!--ASSET:hero--> … <!--/ASSET:hero-->
```

出件器按 `assets.logo` / `assets.hero` 是否留空决定**保留整块还是整块删掉**：

| `assets.*` | 结果 |
|---|---|
| 留空（或整个 `assets` 不写） | 标记连同里面的元素一起删掉，产物里 `<img>` 数为 0 |
| 有值且文件在磁盘上 | 标记剥掉、内容保留、占位符替换成 base64 内联图 |
| 有值但文件不在磁盘上 | **中止出件**（报素材缺失），不出一份缺图的件 |
| 有值但骨架里没有对应插入位 | **中止出件**（报缺插入位），不静默丢图 |

所以**新建产品时 `assets` 两项可以直接留空**：先把内容出通，图片后面补。
出件器只在「提供了图却插不进去」或「指了图却没有图」时才中止——这两种都是
静默丢图的高发处，宁可报错也不许悄悄少一张图。

## 可选关键数字区：`content.json` 的 `stats`

首屏 hero 底部有一条「关键数字带」（大数字计数动画 + 归一条形图）。它是**可选**的：
`content.json` 不写 `stats` 就整块不出，页面回到纯 hero。

```json
"stats": [
  {"value": 12, "label": "专项技能"},
  {"value": 7,  "label": "部品系统"}
]
```

规矩（判据与出件器都会盯）：

- `value` 必须是**数值型**（计数动画按它数；条宽按各值与最大值的比例归一）——给不出数值就别放这条带；
- 每个数字必须能回指出处（写在 `_stats_note` 或事实文件里），**禁止为了好看凑数**；
- 数字终值与条形终宽都写进标签与行内样式：脚本不跑时它们本来就是终态，动画只是加强。

## `sections.html` 契约

- 每段 `<section>` **必须**带 `data-role`，取值 ∈ `pain` / `method` / `evidence` / `diff` / `boundary` / `gap`。
  判据按这个属性做断言；漏了出件器会直接中止并报出来。
- 交互件位置写一行 `<!--INTERACTION-->`，出件器会把所选模板整段包成 section 插进去
  （默认插到所有分节之前；要原地插，在 profile 里声明 `interaction.position: "inline"`）。
- 缺哪一件，就补一段 `data-role="gap"` 并把缺哪一件写在 `data-gap-for` 里；
  **缺件时交互件数必须为 0**——硬凑一个空交互件比没有更糟。

### 最小示例

```html
<section data-role="pain">
  <h2>解决什么问题</h2>
  <h3>现状的毛病</h3>
  <p>……具体到能数出来的痛点，不写形容词。</p>
</section>

<section data-role="method">
  <h2>怎么做到</h2>
  <h3>第一步</h3>
  <p>……</p>
</section>

<!--INTERACTION-->

<section data-role="evidence">
  <h2>实证</h2>
  <p>……每个数值都要能回指到「事实数据」文件里的出处。</p>
</section>

<section data-role="diff">
  <h2>与替代方案的差别</h2>
  <table>
    <tr><th>维度</th><th>替代方案</th><th>本方</th></tr>
    <tr><td>……</td><td>……</td><td>……</td></tr>
  </table>
</section>

<section data-role="boundary">
  <h2>边界与未覆盖</h2>
  <h3>不做什么</h3>
  <p>……说清不做什么，比说做什么更能判断能不能用。</p>
</section>
```

## 建完自检

- 先确认工具链本身是通的：按 `profiles/_示例/README.md` 跑一遍 build → check →
  negative_test，全绿再动自己的配置（示例是全绿的，红了就说明是工具链或环境的问题，
  不是你的配置问题）；
- 品牌色能指出来源 → 否则回到第 2 步问；
- 口径红线非空 → 没有红线的产品也要写明「无红线」并说明理由；
- `assets_dir` 在磁盘上真实存在（回读，不信填写）；
- `python assets/build_demo.py --profile profiles/<产品>/profile.json --out <临时成品>` 能出件；
- `python assets/audit_body.py` 对本产品仍报 0 命中（本体没被这个产品带跑）；
- 目录确实被排除在版本控制外：`git check-ignore -v profiles/<产品>/profile.json` 应有命中
  （默认规则已排除全部产品配置，只放行本目录）。
