# HANDOVER.md — 项目转接手说明

> 用途：WorkBuddy AI 与 Codex 之间转接手本项目时的状态快照与行动清单。
> 最近更新：2026-09-17（WorkBuddy，Codex 额度耗尽期间代管）。

## 0. 先读规则

- 根目录 `AGENTS.md`：全项目强制施工规则（原件只读、不自动接受、commit 需用户明确确认等 30 条）。
- `vault/AGENTS.md`：`study_readonly_pilot`，Claudian 会话内的强制规则。
- 任何与本文件冲突时，以上两份规则优先。

## 1. 当前状态快照（2026-09-17 18:00 验证全绿）

- 已提交阶段：Phase 0 → 1 → 2A → 2B → 2C → 2D-0 → 2E → 3（本地检索）→ **3A（Claudian 只读试点）**，HEAD = `1c6e55c`（`feat: add claudian readonly pilot and handover docs`，2026-09-17 经用户明确确认提交）。
- Claudian 已在 Obsidian 配置完成：Codex provider enabled、`safeMode=read-only`、Native Windows（`vault/.claudian/claudian-settings.json`）。
- 验证基线：health_check 8/8 PASS；validate_vault 47 文件 0 问题；source verify ok；pdf/enhanced verify-output ok；local_search verify ok（含 5 条候选）；run-pilot ok；单元测试 **185 个全过**。

## 2. 本次代管期间 WorkBuddy 的变更（仓库内容已随 1c6e55c 提交）

1. 修复 `vault/90-Parsed-Sources/src-e1df768ce191/pages/page-0002.md` frontmatter：曾被改写成无引号 YAML（疑为 Codex 会话所为），已恢复机器生成的 JSON 引号格式；正文 2076 字符与 parse-report 一致，未动。
2. 按试点配置重建索引：`local_search.py build --rebuild --include-review-candidates`。
   - **坑**：`--rebuild` 不带 `--include-review-candidates` 会导致 run-pilot 预览查不到候选（PILOT_CONTRACT_FAILED）。
3. 新增审核辅助（不入 Git）：
   - `review-queue/src-e1df768ce191-page-0002-comparison.md`：第 2 页三方对照 + 校正清单。
   - `review-queue/src-e1df768ce191-page-0002-corrected-candidate.md`：人工校正转写候选（`manual-corrected-transcription` 1.0.0），结构已对齐 accepted 契约。

## 3. 第 2 页审核结论（详细见对照文件）

- basic（pymupdf）：18 题完整忠实；Q15 上标丢失、Q17 `[x]补` 记法乱码 → 公式题须对照 `assets/page-0002.png`。
- enhanced（MinerU 4.0.0）：Q15 LaTeX 正确；**Q20 题干丢失**、Q17 损坏更重、Q23/Q24 粘连、Q13 丢逗号 → 候选不可接受。
- 处置方案：不接受两个机器候选；改用人工校正转写候选，用户逐题核对后接受。

## 4. 待用户决策事项（接手后先问用户）

1. ~~是否 commit Phase 3A 未提交改动~~ **已于 2026-09-17 完成（1c6e55c）**。
2. 是否接受校正转写候选为第 2 页 accepted 版本。
3. 若接受，是否授权顺手接受第 1、3、4 页（basic 提取，无公式乱码问题，但仍需用户目检）。

## 5. 接受（acceptance）操作手册（无现成脚本，手工步骤）

仅在用户明确说"接受第 2 页校正候选"后执行：

1. 用户逐题核对候选与 `assets/page-0002.png`。
2. 复制候选到 `vault/90-Parsed-Sources/src-e1df768ce191/accepted/pages/page-0002.md`（新建，不覆盖）。
3. 把该文件 frontmatter 的 `review_status` 改为 `"accepted"`（其余键不动，集合必须与 `local_search.py` `_accepted()` 校验一致：`source_id/source_sha256/source_page/derived/review_status/parser_id/parser_version`）。
4. `py -3.12 -B scripts/local_search.py build --rebuild --include-review-candidates`
5. `py -3.12 -B scripts/local_search.py verify` + `search "补码"` 应返回 accepted 结果（不再是"暂无已审核资料"）。
6. `py -3.12 -B scripts/validate_claudian_pilot.py run-pilot` 复验。

## 6. Codex 额度恢复后的第一批动作

1. 读本文件 + `logs/autonomous-progress.json` + `review-queue/` 两个审核文件 + `prompts/handover-to-codex.md`（续接话术）。
2. 先跑只读验证确认真实状态：`health_check.py` / `validate_vault.py` / `local_search.py verify` / `validate_claudian_pilot.py run-pilot`，全绿再继续；有差异先报告，不要自行修复。
3. 与用户确认第 4 节待决策事项。
4. 若 Phase 3A 已提交且 Codex 可用：按 `vault/00-System/Claudian-Study-Pilot-Guide.md` 在 Obsidian 内跑 3 条 UI 试问（人在环，用户手动输入，不要用命令/截图自动化 GUI）。
5. 后续路线：Phase 4（多模型适配、带来源页码的问答）；增强解析器对试卷类双栏密排页面的结构性问题（丢题干、粘连）应记录为解析器评估输入，不要直接重跑覆盖既有候选。

### 接手后明确不要做的事

- 不要重新解析 `src-e1df768ce191`、不要重跑增强解析（目标已存在，解析器会拒绝）。
- 不要重新生成第 2 页校正候选（已存在，接受与否等用户指令）。
- 不要改任何 `review_status`、不要把候选标 accepted。
- 不要擅自 `git commit`；不要批量资料操作。

## 7. 环境要点

- Python 用 `py -3.12 -B`（本机 `python` 指向应用执行别名）；MinerU 固定在 `.venv/mineru` + `models/cache`，日常推理离线。
- 不入 Git 的本地路径：原件、inbox、`config/source-manifests/`、真实基线、review-queue、解析产物、indexes、logs、`.venv`、`models/`、`.obsidian/`、`.claudian/`。
- 检索索引可随时重建；accepted 内容只能通过用户明确审核产生。
- 项目记忆：`.workbuddy-ai/memory/`（WorkBuddy 维护，Codex 可读）。

## 8. 红线（摘自 AGENTS.md，接手即生效）

- 原件永久只读；不得覆盖同名文件；删除需确认且默认归档。
- 不得自动把候选标为 accepted；不得编造内容、引用或页码。
- 未经用户明确确认不得 `git commit`、不得批量资料操作。
- API Key 只走环境变量，不进代码/笔记/日志。
