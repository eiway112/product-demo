# 参与与维护约定

## 改判据的硬要求

1. **每条判据必须能被证明会失败。** 改完判据，同步在 `assets/negative_test.py` 补一条注入，
   注入后核验器必须 FAIL。**不能证明会失败的检查器等于没有检查器**——它只是印了个绿字。
   这条**由机器守**：负向测试末行的覆盖率判据会点名「本次参数下跑得到、却没有注入用例」的判据
   并 FAIL。判据族里如有注入真动不了的纯函数断言，登记进 `UNIT_PROVEN`，
   由 `check_demo.py --self-test` 证明（该名单现在为空——V7 补上像素校验后注入已动得了它）。
   补注入时同时注意**换一种失效形态**——判据与注入共用盲区时，测试只证明它们一起错在哪。
2. **改断言前先问它答的是哪个问题**：只回答「出现过吗」的检查，守护不了「一致吗」；
   只判「文件非空」的检查，守护不了「图渲染出来了」。
3. **负向测试要带 `--chrome` 再跑一遍**：离线路径与浏览器路径落在核验器不同的返回分支上，
   只跑离线会漏掉浏览器侧的全部改动。
4. **断言必须与目标性质同层**：源码层文本 ≠ 渲染层效果。凡「改了配置 / 样式 / 规则」的
   完成声明，验证手段必须能观测到**改动生效后的那一层**。
5. **缺条件要列 SKIP，不许静默消失。**「没检查」与「检查过且干净」必须能分开读。

## 提交前跑什么

```bash
# 出件（用仓内自带示例，无需自建配置）
python assets/build_demo.py --profile profiles/_示例/profile.json --out <临时目录>/demo.html

# 离线判据（--expect：把文档里的数字变成机器断言，交付与 CI 必须带）
python assets/check_demo.py <临时目录>/demo.html --profile profiles/_示例/profile.json --img 0 \
  --expect pass=24,fail=0,skip=3

# 浏览器判据（--js-value IXRDY 是契约 C6 的取证锚点；不给它，JS 执行那条判据只会列 SKIP）
#   --chrome 的路径用 find_chrome.py 取：跨平台枚举标准安装位置，找不到即 exit 1
python assets/check_demo.py <临时目录>/demo.html --profile profiles/_示例/profile.json --img 0 \
  --chrome "$(python assets/find_chrome.py)" --js-value IXRDY --expect pass=28,fail=0,skip=3

# 负向测试（29 条用例，每条都必须被拦下；末行还判注入覆盖率）
python assets/negative_test.py <临时目录>/demo.html --profile profiles/_示例/profile.json --img 0 \
  --chrome "$(python assets/find_chrome.py)" --js-value IXRDY

# 单测：判据里的纯函数断言（如 V7 的像素校验）在这里被证明会失败
python assets/check_demo.py --self-test

# 本体清洁度
python assets/audit_body.py
python assets/audit_body.py --self-test
```

**每一步的预期输出（含具体数字）写在三份示例各自的 `README.md` 里——
`profiles/_示例/`、`profiles/_示例-带图/`、`profiles/_示例-inline/`。**
跑完对一遍——文档里的数字若与实测不符，改文档，别改实测。

另外两份示例也要各跑一遍，它们各补一个盲区：

- `_示例-带图/`（带图、catalog 形态，`--img 2`）：B2 / V2 的注入点在它上面才真的执行得到；
- `_示例-inline/`（交互件嵌在正文里）：出件器的 inline 分支此前在仓内没有任何配置声明过，
  属于「有代码、从未被走过」；判据 I4 会比对声明位置与成品里交互件实际的次序，挪错位置必 FAIL。

## 本体与产品配置的边界

| 位置 | 身份 | 规则 |
|---|---|---|
| `SKILL.md` + `assets/**` | **本体** | 跨产品不动。新增产品后 `git diff --stat -- SKILL.md assets/` 应为 0 行 |
| `profiles/<产品>/` | **产品配置** | 默认不入库（`.gitignore` 排除）；由使用者自行纳管版本 |
| `profiles/_*/`（`_模板/` + 三份示例） | **基础设施** | 下划线前缀即标记，随库入库 |

**本体里不得出现任何具体产品名**。这条不靠自觉，靠 `assets/audit_body.py` 扫（词表自动从
`profiles/*/profile.json` 收集，脚本自身不写死任何产品名）——以及结构签名：一个产品名都不出现，
产品专属的字段结构组合照样可能被焊在骨架里。

## 新增交互件形态

`assets/interaction_patterns.md` 的 §五 写了规格型 / 流程型两类未建模板的实现规范。
实现新模板时：

1. 逐条满足 §三 的 **C1–C7**（C7 是卡片索引与标题容器的取证面，没有它 V8 判不了往返）；
2. 补一条负向注入，证明它的默认态**可被证伪**（建议直接复用「整块脚本被掏空」那条形态）；
3. 在 `profiles/_示例/` 或另建一份下划线目录的示例，让它变成**任何人可复现**的——
   仓内没有示例的模板，它的可用性只有维护者本机能核。

## 发布前检查

RC1–RC7 全部由 `python assets/release_check.py` 机器判（它会 FAIL，不靠勾选）：

- [ ] **RC1** `SKILL.md` frontmatter 的 `version` == `manifest.json` 的 `version` == `CHANGELOG` 顶部
      ——技能平台读的是 `SKILL.md` 的 frontmatter。v1.4.0 之前 SKILL.md 写着 1.2.0 而 manifest
      是 1.3.0，而当时的发布清单里没有一条会拦住它（release_check 的 RC1 就是为此装的）
- [ ] **RC2** manifest 登记的 factory_components 全部存在
- [ ] **RC3** 仓内无 `__pycache__` / `_negtest` / 临时成品残留
- [ ] **RC4 / RC5** 三份示例配置内容包齐全 **且真的会入库**
      ——RC4 只查「文件在不在磁盘上」，RC5 查「`.gitignore` 会不会把它排除」。
      两者缺一就会出现「本地有、干净克隆没有」：`_示例-带图/` 就是这样被漏掉的。
      **新增下划线开头的示例目录时，放行规则必须是模式化的（`!profiles/_*/`），不要去枚举名字**
- [ ] **RC6 / RC7** 源仓与运行态副本逐文件一致 **且 CI 配置不会在 Windows 腿翻车**
      ——RC6 管「改完有没有搬到宿主真正加载的那一处」（同步命令见 SKILL.md 第 13 条）；
      RC7 管顶层 `PYTHONIOENCODING: utf-8` 与 `run:` 块不写反斜杠续行。
      两条都由真实事故换来：前者是副本落后 5 个 commit 而无人察觉，
      后者是 CI 首跑 windows 两条腿全红、四条 Unix 腿全绿。
- [ ] `manifest.json` 的 `version` / `updated_at` / `repository_url` 已更新
- [ ] `CHANGELOG.md` 记了本次变更（只记已发生的）
- [ ] 上面每条命令全绿，且三份示例 README 里的预期数字与实测一致
- [ ] `python assets/audit_body.py` 报 0 命中
- [ ] `python assets/audit_body.py --self-test` 三族各自被证明有效
- [ ] `python assets/check_demo.py --self-test`（注入动不了它的那些断言）
