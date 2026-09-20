# `_示例-带图/` — 第二份示例配置（带图 + 能力型）

**它为什么存在**：第一份示例（`../_示例/`）刻意不配图、配计算型，于是留下两个盲区——

1. **B2 / V2 两条判据在干净克隆里永远列 SKIP**（没有图可判，「图片全部内联且能解码」这条等于没查过）；
2. **`catalog.html`（能力型）模板的可用性只有维护者本机能核**——它的 ✅ 此前没有仓内可复现输入。

本目录补的正是这两处：两张极小的 PNG（纯色块，不塞二进制素材）+ 能力型的 `items.json`。
跑通之后，「带图」与「第二种交互形态」这两条链路在干净克隆里同样任何人可复现。

**它不是**新建产品的起点——新建请复制 `../_模板/`。两份示例的差异只在形态与素材，
其余契约完全一致（叙事五要件、交互件契约 C1–C7、判据口径都不因示例而变）。

## 跑通它

```bash
python assets/build_demo.py --profile profiles/_示例-带图/profile.json --out demo2.html
python assets/check_demo.py demo2.html --profile profiles/_示例-带图/profile.json --img 2 \
  --expect pass=25,fail=0,skip=2
python assets/negative_test.py demo2.html --profile profiles/_示例-带图/profile.json --img 2
python assets/check_demo.py demo2.html --profile profiles/_示例-带图/profile.json --img 2 \
  --chrome "<chromium 路径>" --js-value IXRDY --shot <png 路径> \
  --expect pass=30,fail=0,skip=1
```

（`--img 2`：本示例刻意配两张图，所以契约图数是 2。）
出件时会打印每张素材的**绝对路径与 sha256 前 12 位**——那是「这次取的是哪一份」的回读依据。

### 预期输出（离线）

| 命令 | 预期 |
|---|---|
| `build_demo` | 退出码 0，打印两行「素材 <key> <路径> sha256 …」，成品约 2.2 万字节，交互件 catalog，section 5 段 |
| `check_demo`（离线） | `PASS 25 / FAIL 0 / SKIP 2`；两条 SKIP：V9（成品未渲染关键数字区）＋ 浏览器那组（未给 `--chrome`） |
| 带 `--chrome --js-value` | `PASS 29 / FAIL 0 / SKIP 2`（V8 交互往返也进来；V7 仍 SKIP，未请求截图；另一条是 V9） |
| 再加 `--shot` | `PASS 30 / FAIL 0 / SKIP 1`（唯一剩下的 SKIP 是 V9） |
| `negative_test`（离线 / 带 `--chrome`） | 29 条用例，退出码 0（离线 24 通过 5 跳过 / 带浏览器 28 通过 1 跳过）；B2 / V2 两条注入**真的执行**（有图可注），不再列 SKIP；V7 的空白截图注入在带浏览器那轮真跑并必须被拦下 |
| `check_demo`（带 `--expect`） | `--expect pass=25,fail=0,skip=2` 成立——数字由机器断言，不是文档里的一句话 |

与 `_示例/` 的数字不同是正常的：本示例多两张图（V2 由 SKIP 变 PASS），少一条浏览器 SKIP。

## 图片的来历

两张 PNG 由脚本生成（纯色块，240x60 与 640x270，合计不到 1.2 KB），
目的是把 B2 / V2 的注入点做出来，**不是**用来演示版式。
