# HANDOVER.md — 项目转接手说明

> 用途：WorkBuddy AI 与 Codex 之间转接手本项目时的状态快照与行动清单。
> 最近更新：2026-09-17（Codex，Phase 3B 与个人学习入口整理）。

## 0. 先读规则

- 根目录 `AGENTS.md`：全项目强制施工规则（原件只读、不自动接受、中文学习入口优先等）。
- `vault/AGENTS.md`：`study_readonly_pilot`，Claudian 会话内的强制规则。
- 任何与本文件冲突时，以上两份规则优先。

## 1. 当前状态快照

- Phase 3B 已提交：HEAD 至少包含 `a1feca9`（`feat: add manual review and acceptance`）。接受、撤销、验证和状态使用 `scripts/review_manager.py`，不得再手工复制 accepted 文件。
- Claudian 已在 Obsidian 配置完成：Codex provider enabled、`safeMode=read-only`、Native Windows（`vault/.claudian/claudian-settings.json`）。
- 当前真实 accepted 页面为 0；第 2 页有 basic、MinerU 和人工校正三个待审核候选。
- 最近验证：health_check 通过；validate_vault 51 文件 0 问题；source、pdf、enhanced、review 和 local_search 验证通过；run-pilot 通过；单元测试 **198 个全过**。

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

## 4. 待用户决策事项

1. 是否逐题核对并接受第 2 页人工校正候选。
2. 第 1、3、4 页只有在用户逐页目检并明确授权后才能接受，不得顺手批量接受。

## 5. 接受操作手册

仅在用户明确说"接受第 2 页校正候选"后执行：

1. 用户逐题核对候选与 `assets/page-0002.png`。
2. 先运行 `review_manager.py accept` 默认 dry-run，核对 source_id、页码、候选路径与哈希。
3. 只有用户明确授权后才追加 `--apply`；工具创建不可覆盖快照和接受事件。
4. 运行 `review_manager.py verify`，再显式重建并验证本地索引。
5. 撤销必须使用 `review_manager.py revoke`；只追加撤销事件，不删除历史快照。

## 6. 日常入口

1. 从 `vault/学习主页.md` 开始。
2. `vault/教材资料.md` 提供当前资料、原始页预览和候选入口。
3. `vault/日常辅导.md` 区分一般讲解、指定候选辅导与严格资料查询，并提供可复制提示词。
4. 当前 Claudian 维持 read-only；保存笔记时在聊天中生成 Markdown，再由用户复制到中文知识笔记或错题目录。

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
