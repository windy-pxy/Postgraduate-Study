# 数学一 + 408 Obsidian AI 考研学习系统

为未来 1～2 年的数学一与 408 学习建立本地、可迁移、可审阅的资料与笔记基础。最终运行不依赖 ChatGPT；后续计划通过适配器支持 DeepSeek、Claude、OpenAI 兼容 API 和本地模型。

## 当前阶段

Phase 0 至本地公式增强和可追溯页级检索已提交。MinerU 4.0.0 已在项目隔离环境中跑通合成页和一个授权真实异常页；结果仍是待审核候选。当前 Phase 3A 建立 Claudian 2.2.7 + Codex 的只读学习问答试点，插件只允许经 Obsidian 官方社区插件 UI 安装，问答不得自动接受候选或修改资料。

Phase 0 工具只用标准库；Phase 1 验证器使用本机已有的 PyYAML 6.0.3，本次不安装依赖。迁移后若缺少 PyYAML，工具会明确提示，不会自动安装。

Phase 2A 的 `scripts/source_manager.py` 只使用 Python 标准库，CLI 直接执行脚本即可。完整中文指南在 `vault/00-System/Source-Import-Guide.md`。

Phase 2B 使用本机已有的 PyMuPDF 1.26.7，并在 `requirements.txt` 固定版本；本次没有创建 `.venv` 或安装软件。迁移环境如需安装，只允许在项目内 `.venv` 中按 requirements 安装，不得改全局 Python。PDF 解析说明见 `vault/00-System/PDF-Parsing-Guide.md`。

公式增强器使用 `.venv/mineru`、项目内模型缓存和 `config/mineru-4.0.requirements.lock.txt`。安装时允许联网下载；日常推理强制使用本地模型并阻止 socket 连接。命令、模型身份、输出结构与限制见 `vault/00-System/Enhanced-Parsing-Guide.md`。

页级检索使用 Python 自带 SQLite FTS5，不需要大模型或网络服务。默认只查 accepted 页面；显式预览参数才能查看未审核基础/增强候选。索引位于被忽略的 `indexes/`，可从来源和派生文件重建。详见 `vault/00-System/Local-Retrieval-Guide.md`。

Claudian 试点规则位于 `vault/AGENTS.md`，使用说明见 `vault/00-System/Claudian-Study-Pilot-Guide.md`。Claudian 的 Codex Provider 必须显式设置为 read-only；提供器请求会发送到 OpenAI，禁止把原始资料或未审核全文作为附件发送。

## 目录用途

| 目录 | 用途 |
| --- | --- |
| `vault/00-System` | 系统说明与学习导航 |
| `vault/01-Math1/Calculus` | 高等数学 |
| `vault/01-Math1/Linear-Algebra` | 线性代数 |
| `vault/01-Math1/Probability` | 概率论与数理统计 |
| `vault/02-408/Data-Structure` | 数据结构 |
| `vault/02-408/Computer-Organization` | 计算机组成原理 |
| `vault/02-408/Operating-System` | 操作系统 |
| `vault/02-408/Computer-Network` | 计算机网络 |
| `vault/03-Knowledge-Notes` | 跨章节知识笔记；`AI-Drafts` 仅存经明确请求生成的草稿 |
| `vault/04-Mistakes` | 错题记录 |
| `vault/05-Past-Papers` | 历年真题学习笔记 |
| `vault/06-Stage-Tests` | 阶段测评记录 |
| `vault/07-Weakness-Analysis` | 薄弱点分析 |
| `vault/08-Study-Records` | 学习日志与复习记录 |
| `vault/80-Attachments` | 笔记附件 |
| `vault/90-Parsed-Sources` | 派生的解析资料，非原件 |
| `vault/99-Templates` | 笔记模板 |
| `sources-original/math1`、`sources-original/408` | 永久只读的原始资料存放位置 |
| `import-inbox` | 待用户确认的导入候选 |
| `review-queue` | 待人工审核的产物 |
| `archive` | 经确认后移入的非原始旧文件 |
| `scripts` | 项目脚本 |
| `config` | 配置样例 |
| `config/source-manifests` | 每个 source_id 一份本地 JSON 来源清单，不含正文且不进入 Git |
| `review-queue/import-plans` | 待审核的单文件导入计划 |
| `review-queue/pdf-parse-blocks` | 解析因高置信疑似密钥被阻止时的无原文安全报告 |
| `review-queue/parsing-routing` | 无正文的页面质量路由计划 |
| `review-queue/parsing-jobs` / `parsing-checkpoints` | 未来单页队列和断点，运行内容不入 Git |
| `prompts` | 后续提示词 |
| `tests` | 基础安全测试 |
| `logs` | 本地运行日志，不入 Git |

原始资料保留原貌，任何程序和 AI 不得修改、覆盖、移动或删除。解析资料是后续从原件生成的可追溯派生文件；修改解析文本不会修改原件。个人 Markdown 笔记可在授权范围内编辑。空目录以 `.gitkeep` 保留。

Git 只保存可复用的系统代码、测试、配置样例、系统文档、模板和用户主动创建的正式知识笔记。真实原件、inbox 文件、来源清单、真实 SHA-256 基线、导入/路由计划、解析产物、运行队列、日志和模型缓存只保留在本机。`config/sources-original.baseline.example.json` 是空结构说明；实际完整性校验始终读取本地且被忽略的 `config/sources-original.baseline.json`。忽略规则不是备份，动态资料仍需独立备份。

## 使用与验证

在 Obsidian 中选择“打开文件夹作为仓库”，打开 `D:\Postgraduate-Study\vault`。Phase 3A 仅安装官方社区插件 Claudian；无需把整个项目作为 Obsidian 仓库。

从 `00-System/Home.md` 开始，先读 `Metadata-Schema.md` 和 `Linking-Rules.md`。在 `99-Templates/Templates-MOC.md` 选择模板，手动复制到相应正式笔记目录；设置唯一 id，按实际情况填写，清除占位符后运行验证。导航页和模板不代表实际学习进度。详细检查范围和错误说明见 `00-System/Validation-Guide.md`。

在项目根目录 PowerShell 中执行：

```powershell
py -3.12 -B scripts/health_check.py
py -3.12 -B scripts/validate_vault.py
py -3.12 -B scripts/source_manager.py verify
py -3.12 -B scripts/pdf_parser.py --help
py -3.12 -B scripts/enhanced_parser.py model-status
py -3.12 -B scripts/local_search.py --help
py -3.12 -B scripts/validate_claudian_pilot.py run-pilot
py -3.12 -B -m unittest discover -s tests -v
git status --short
git diff --stat
```

本机 `python` 命令可能指向 Windows 应用执行别名，已采用 `py -3.12`。`-B` 避免生成 Python 缓存。历史测试使用内存模拟；Phase 2A 测试在项目内 `tests/.runtime/` 创建独占临时沙箱和合成 PDF/Office 容器，再清理自身生成物，不修改实际原件。健康检查和 Vault 验证都接入完整性验证：流式读取原件二进制进行 SHA-256 与签名检查，不解析正文、不读取 `.env` 或密钥环境变量。退出码 0 表示通过，1 表示发现问题。

## Phase 2A 导入流程

正式支持 `.pdf`、`.pptx`、`.docx`，其他格式标记 unsupported。扩展名与签名/Office 结构不一致则拒绝。用户将资料放入 `import-inbox/`，明确指定 course、subject、source_type；不猜测分类，不使用 AI。

以下是以后经授权导入时的命令示意，尖括号必须替换为实际值；本阶段不执行真实导入：

```powershell
py -3.12 -B scripts/source_manager.py scan
py -3.12 -B scripts/source_manager.py plan "import-inbox/<文件.pdf>" --course math1 --subject calculus --source-type textbook
py -3.12 -B scripts/source_manager.py plan "import-inbox/<文件.pdf>" --course math1 --subject calculus --source-type textbook --save
py -3.12 -B scripts/source_manager.py apply --plan "review-queue/import-plans/<计划ID>.json"
py -3.12 -B scripts/source_manager.py apply --plan "review-queue/import-plans/<计划ID>.json" --apply
py -3.12 -B scripts/source_manager.py verify
py -3.12 -B scripts/source_manager.py baseline-update
py -3.12 -B scripts/source_manager.py baseline-update --apply
py -3.12 -B scripts/source_manager.py list
py -3.12 -B scripts/source_manager.py status
```

plan 默认预览，`--save` 只保存计划；apply 默认预演，`--apply` 才复制原件并登记。每次只指定一份计划。分类不完整的计划进入待审核状态，不能执行。成功后 inbox 和计划均保留；不删除或移动。每个子命令支持 `--help`。

source_id 为 `src-` 加 SHA-256 前 12 位，冲突时逐位延长。完整 SHA-256 写入清单；同一内容改名仍是同一来源，不重复导入。同名不同内容存入不同 source_id 目录。原件和 JSON 清单均先写同目录临时文件，再校验并原子发布，禁止覆盖。Windows 只读属性未设置，即使设置也不是强安全边界；Windows ACL 尚未启用。

基线版本 2 记录已确认来源的 SHA-256、路径及辅助大小。apply 不更新基线；新来源显示 baseline_pending，只有单独 `baseline-update --apply` 才补充锚点。更新前必须通过全部原件、清单和已有锚点检查，不允许改写旧哈希来掩盖异常。

发现原件被修改、丢失、未登记文件、清单异常或哈希冲突时，停止后续写入，保留现场并人工检查可信备份与历史。禁止删除或重建基线消除报错。原件已发布而清单失败时，保留原件并报告异常；本阶段不实现自动修复。暂存锁或异常临时文件也不得擅自清理。

## Phase 2B 本地 PDF 解析

解析器只接受来源清单中已登记、完整性通过且 file_type 为 pdf 的 source_id，不接受路径参数。`inspect` 只读查看页数；`parse` 默认 dry-run，只有 `parse <source_id> --apply` 创建派生目录。目标目录存在即拒绝，不覆盖或合并。

```powershell
py -3.12 -B scripts/pdf_parser.py inspect <source_id>
py -3.12 -B scripts/pdf_parser.py parse <source_id>
py -3.12 -B scripts/pdf_parser.py parse <source_id> --apply
py -3.12 -B scripts/pdf_parser.py verify-output <source_id>
py -3.12 -B scripts/pdf_parser.py report <source_id>
```

输出固定在 `vault/90-Parsed-Sources/<source_id>/`，包括 `index.md`、`pages/page-0001.md`、必要的 `assets/page-0001.png`、`parse-report.json` 与 `review.md`。所有页面标记为 derived 和 review_required。普通提取文本放在 Markdown 文本围栏中忠实保留；疑似公式/图形只标记 needs_formula_review，绝不自动伪造公式。每页错误保留占位和固定错误码，不静默跳过。

解析器只在原件 SHA-256、临时产物验证和原子发布都成功后，原子更新对应 manifest 的 parser 字段为 `parsed`、解析器、页数、时间、项目内输出路径和 `review_required`，不改原有来源身份、哈希、分类和导入信息。验证器会报告目录与 manifest 状态、页数或报告不一致。

工具不对派生正文做自动脱敏或改写。高置信疑似真实密钥会阻止整份产物发布，manifest 保持 `not_started`，并且只在 `review-queue/pdf-parse-blocks/` 记录无原文的错误码、页码和风险类型。`YOUR_API_KEY` 等占位符和普通代码示例保持原样。

`verify-output` 核对来源哈希、PDF 页数、输出页数、逐页元数据、报告指标、PNG 资源、文件全集和内部链接，拒绝绝对/越界链接、未登记页面、未转义 LaTeX 与常见敏感模式。它检查结构一致性，不证明文字内容准确。详细流程、质量报告和首次真实验证建议见 `vault/00-System/PDF-Parsing-Guide.md`。

Phase 2C 命令只读校验配置或从已验证的基础产物生成无正文路由计划：

```powershell
py -3.12 -B scripts/parsing_architecture.py validate-config
py -3.12 -B scripts/parsing_architecture.py plan-source <source_id> --profile cs408_symbol_dense
py -3.12 -B scripts/parsing_architecture.py verify-plan <source_id>
```

三种档案、分层目录、状态机和未来 MinerU 接入边界见 `vault/00-System/Scalable-Parsing-Architecture.md`。

Phase 2D-0 在现有 manifest、路由计划和队列元数据上做 dry-run 规划：

```powershell
py -3.12 -B scripts/parsing_architecture.py source-status --course 408
py -3.12 -B scripts/parsing_architecture.py batch-plan --course 408 --subject computer-organization
py -3.12 -B scripts/parsing_architecture.py estimate-resources --profile cs408_symbol_dense
py -3.12 -B scripts/parsing_architecture.py queue-status
py -3.12 -B scripts/parsing_architecture.py resume-check --source-id <source_id>
py -3.12 -B scripts/parsing_architecture.py retry-page <source_id> <页码>
```

`batch-plan` 默认只输出计划，`--save` 也只保存队列元数据，不启动解析。无任何筛选的全库计划必须额外给出 `--confirm-all-sources`。默认每批最多 25 页、并发 1，重型增强批次与基础批次严格分开。完整说明见 `vault/00-System/Batch-Parsing-Guide.md`。

Phase 2E 的单页增强命令默认 dry-run，只处理已进入增强队列的页面：

```powershell
py -3.12 -B scripts/enhanced_parser.py inspect <source_id> <页码>
py -3.12 -B scripts/enhanced_parser.py parse <source_id> <页码>
py -3.12 -B scripts/enhanced_parser.py parse <source_id> <页码> --apply
py -3.12 -B scripts/enhanced_parser.py verify-output <source_id> <页码>
```

目标存在时拒绝覆盖。增强候选包含原页预览、模型 Markdown、结构化结果、运行指标、候选清单和审核清单；真实产物继续被 Git 忽略。

Phase 3 最小本地检索闭环：

```powershell
py -3.12 -B scripts/local_search.py build
py -3.12 -B scripts/local_search.py status
py -3.12 -B scripts/local_search.py search "关键词"
py -3.12 -B scripts/local_search.py search "关键词" --source-id <source_id> --page <页码> --include-review-candidates
py -3.12 -B scripts/local_search.py verify
```

当前没有人工接受页面时，默认查询明确返回“暂无已审核资料”。预览候选需要建库与查询两处均显式指定，结果标明 `UNREVIEWED_CANDIDATE`。

## Phase 3A Claudian 只读学习问答

当前试点使用本机 Codex CLI 的现有 ChatGPT 登录，不在仓库中保存 API Key。安装必须通过 Obsidian“设置 → 社区插件 → 浏览 → Claudian → 安装 → 启用”，并在 Claudian 的 Codex 设置中选择 Native Windows 和 read-only，聊天栏权限必须显示 Safe。默认的 workspace-write 不符合本项目要求；不得启用 YOLO、MCP、子代理、Collab 或其他 Provider。候选预览允许在 read-only 沙箱内列目录、搜索和读取 vault Markdown，但禁止运行项目脚本、写入、下载、安装或联网命令。

项目侧验证命令：

```powershell
py -3.12 -B scripts/validate_claudian_pilot.py check-policy
py -3.12 -B scripts/validate_claudian_pilot.py run-pilot
```

验证脚本不调用模型，只确认正式问答与候选预览的边界。UI 首次试问、预期回答、隐私边界和故障停止条件见 `vault/00-System/Claudian-Study-Pilot-Guide.md`。

## 后续路线（每阶段开始前确认）

1. Phase 1（本阶段）：Obsidian 学习数据结构、笔记模板、双链规范与只读验证；不导入资料。
2. Phase 2A（已提交）：安全导入与 SHA-256 来源清单；Phase 2B（本阶段）：数字原生 PDF 基础文本与审核产物；后续子阶段：OCR、公式、复杂图表和其他 Office 格式。
3. Phase 3：本地检索与来源追溯。
4. Phase 4：多模型适配、带来源和页码的知识问答。
5. Phase 5：错题、复习记录和阶段测评流程。
6. Phase 6：薄弱点分析、长期维护、备份和恢复验证。

## 安全注意事项

所有层级的 `.obsidian/` 和 `.claudian/` 目录及其内容均保留在本地，不进入 Git，不因忽略规则而删除或移动。前者保存 Obsidian 插件与设备配置，后者保存 Claudian 的 vault 设置、会话和运行状态。

Phase 1 的路径/大小/时间基线已在原件区为空且旧验证通过时升级。当前使用 SHA-256 判断内容一致性，大小和时间不能替代它。SHA-256 不是数字签名，不抵御有权限同时篡改原件、清单和基线的人，不能宣称为强防篡改机制；保留可信 Git 历史和独立备份仍有必要。Windows ACL 尚未启用。

遵守 `AGENTS.md`。任何删除必须明确确认，普通删除默认归档；原件永不删除。禁止未经确认的批量资料操作。创建文件不得覆盖同名文件；编辑前检查 Git 状态。API Key 仅由环境变量提供，不写入任何笔记、样例或日志。`.env.example` 只能保留空值。配置中的 `api_key_env` 仅引用变量名称。

`.gitignore` 排除原件、真实来源清单与基线、导入/路由计划、解析产物、运行队列、敏感文件、日志、模型缓存、测试沙箱及全部 Obsidian 配置，但不能阻止强制添加，也不能替代提交前审计。代码、配置样例、系统文档、模板和正式知识笔记可以跟踪。写入仅限项目内，拒绝链接、目录联接、路径穿越和项目外路径；并发锁只保护本工具，不替代操作系统权限。工具不持久化运行日志，错误仅输出固定代码，不输出正文、密钥或底层异常的绝对路径。不得擅自提交或开始后续阶段。
