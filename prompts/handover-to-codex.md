# 交接提示词：WorkBuddy → Codex（续接版 v2，2026-09-17）

> 用法：Codex 额度恢复后，把 `---` 之后整段粘贴到 Codex 会话开头。Codex 看不到本 WorkBuddy 会话，本段自包含。
> 设计原则：`HANDOVER.md` 是唯一权威状态源；本段只做"指路 + 精确续接点 + 反偏离护栏"。

---

你正在接手本地考研学习项目（数学一 + 408，Obsidian），项目根 `D:\Postgraduate-Study`。你上一次 Codex 会话在"Claudian 配置已完成、正要开始 UI 问答试点"时因额度用尽 + 上下文压缩中断；**中断期间由另一个助手（WorkBuddy）代管并做了一些改动**。请先按顺序读以下文件，再向我确认，不要凭记忆或重做已完成的事：

1. `D:\Postgraduate-Study\HANDOVER.md` —— **唯一权威状态源**，凡与本提示不一致以它和 AGENTS.md 为准。
2. `D:\Postgraduate-Study\logs\autonomous-progress.json` —— 你之前的进度记录。
3. `D:\Postgraduate-Study\review-queue\src-e1df768ce191-page-0002-comparison.md` —— 第 2 页三方对照 + 校正清单。
4. `D:\Postgraduate-Study\review-queue\src-e1df768ce191-page-0002-corrected-candidate.md` —— 人工校正转写候选。
5. `D:\Postgraduate-Study\vault\00-System\Claudian-Study-Pilot-Guide.md` —— 重点看"首次试点"的 3 条测试问题。
6. `D:\Postgraduate-Study\vault\AGENTS.md` 与 `D:\Postgraduate-Study\AGENTS.md` —— 强制规则。

## 你离开期间，WorkBuddy 代管做了什么（不要当成"未完成"去重做）

1. 修复 `vault/90-Parsed-Sources/src-e1df768ce191/pages/page-0002.md` 的 frontmatter：它曾被改成无引号 YAML（疑似你上次会话留下的，修改时间与中断时间吻合），已恢复机器生成格式，正文未动。
2. 重建了检索索引：`py -3.12 -B scripts/local_search.py build --rebuild --include-review-candidates`。
3. 产出第 2 页两份审核材料（上面的 3、4 号文件）：三方对照 + 人工校正转写候选（parser_id `manual-corrected-transcription`），后者结构已对齐 accepted 契约。
4. 增补 `.gitignore`：`/review-queue/*.md` 与 `/.workbuddy-ai/`（此前未被忽略）。
5. 经用户确认提交：HEAD = `1c6e55c`（`feat: add claudian readonly pilot and handover docs`），工作区只剩两个未提交项：`HANDOVER.md`（准确性修订）和 `prompts/handover-to-codex.md`（本文件），**不要擅自提交**，等用户指令。

## 先确认真实状态（只读命令，别改任何东西）

```
py -3.12 -B scripts/health_check.py
py -3.12 -B scripts/validate_vault.py
py -3.12 -B scripts/local_search.py verify
py -3.12 -B scripts/validate_claudian_pilot.py run-pilot
```

预期全绿：健康检查 8/8、Vault 47 文件 0 问题、检索 verify ok、run-pilot 契约通过（正式查询返回"暂无已审核资料"，预览 basic/enhanced 分离）。若哪项不绿，先停下来向我报告差异，不要自行修复。

## Claudian 配置现状（已完成，别重做）

`vault/.claudian/claudian-settings.json` 已核对正确：Codex `enabled=true`、`safeMode=read-only`、权限 `normal`、Claude/Collab 关闭、无环境变量无密钥。注意：你上次面板写"CLI 路径留空"，但文件里 `codex.cliPath` 已被自动发现填成 `...\OpenAI\Codex\bin\...\codex.exe`，**保持现状别改回空**。`.claudian/` 已被 `.gitignore` 忽略。

## 你下一步唯一要做的：Claudian UI 内 3 条试问（Phase 3A 最后环节）

按 `Claudian-Study-Pilot-Guide.md` "首次试点"：

1. `请按 study_readonly_pilot 正式回答：补码。` → 预期"暂无已审核资料"（现在无 accepted 页面，属正确行为）。
2. `预览待审核候选：只查 source_id src-e1df768ce191 第 2 页中的补码，分别列出 basic 与 enhanced，不要总结为教材事实。` → 预期逐项带 `review_required`/`source_id`/页码/`parser_id`/`parser_version` + 双链，basic 与 enhanced 分离。
3. 点双链 → 分别定位基础页与增强候选。

工作方式：**不要用命令/截图自动化 Obsidian GUI**（上次多显示器 DPI 下已证明不稳）。你只产出 3 条问题 + 每条的预期答案与判定标准，**由用户手动输入并回贴结果**，你逐条判定。若 Claudian 请求写入/执行命令/提权/联网 → 判定试点失败；正式问答引用候选或合并版本 → 判定不通过。

## 反偏离护栏（务必遵守）

- **不要**重新解析 `src-e1df768ce191`、不要重跑增强解析（基础/增强目标已存在，解析器会拒绝；重跑也不解决本页"丢题干/粘连"的结构问题）。
- **不要**重新生成第 2 页校正候选（已存在，是否接受等我指令）。
- **不要**把候选标为 accepted、不要改任何 `review_status`。
- **不要**执行 `git commit`（除非我明确说"提交"）。
- **不要**把 UI 试问和候选接受混在一起做——它们是两条独立工作流。
- 红线：原件只读；不覆盖同名文件；不编造内容/引用/页码；API Key 只走环境变量；脚本用 `py -3.12 -B`；重建索引必须带 `--include-review-candidates`。

请先复述：你读到的当前状态、你离开期间被改动了什么、以及你理解的下一步。等我确认后再动手。
