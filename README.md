# 数学一 + 408 Obsidian AI 考研学习系统

为未来 1～2 年的数学一与 408 学习建立本地、可迁移、可审阅的资料与笔记基础。最终运行不依赖 ChatGPT；后续计划通过适配器支持 DeepSeek、Claude、OpenAI 兼容 API 和本地模型。

## 当前阶段

Phase 0、Phase 1 已验收并提交。Phase 2A 建设安全导入基础设施、SHA-256 完整性校验和来源清单；本阶段只运行合成测试，没有导入真实学习资料。尚未实现正文解析、检索、问答、模型调用或自动学习分析，不安装插件，不执行 Git 提交。Phase 2B 才会开始正文解析。

Phase 0 工具只用标准库；Phase 1 验证器使用本机已有的 PyYAML 6.0.3，本次不安装依赖。迁移后若缺少 PyYAML，工具会明确提示，不会自动安装。

Phase 2A 的 `scripts/source_manager.py` 只使用 Python 标准库，CLI 直接执行脚本即可。完整中文指南在 `vault/00-System/Source-Import-Guide.md`。

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
| `vault/03-Knowledge-Notes` | 跨章节知识笔记 |
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
| `config/source-manifests` | 每个 source_id 一份 JSON 来源清单，不含正文 |
| `review-queue/import-plans` | 待审核的单文件导入计划 |
| `prompts` | 后续提示词 |
| `tests` | 基础安全测试 |
| `logs` | 本地运行日志，不入 Git |

原始资料保留原貌，任何程序和 AI 不得修改、覆盖、移动或删除。解析资料是后续从原件生成的可追溯派生文件；修改解析文本不会修改原件。个人 Markdown 笔记可在授权范围内编辑。空目录以 `.gitkeep` 保留。

## 使用与验证

在 Obsidian 中选择“打开文件夹作为仓库”，打开 `D:\Postgraduate-Study\vault`。不需要安装插件。无需把整个项目作为 Obsidian 仓库。

从 `00-System/Home.md` 开始，先读 `Metadata-Schema.md` 和 `Linking-Rules.md`。在 `99-Templates/Templates-MOC.md` 选择模板，手动复制到相应正式笔记目录；设置唯一 id，按实际情况填写，清除占位符后运行验证。导航页和模板不代表实际学习进度。详细检查范围和错误说明见 `00-System/Validation-Guide.md`。

在项目根目录 PowerShell 中执行：

```powershell
py -3.12 -B scripts/health_check.py
py -3.12 -B scripts/validate_vault.py
py -3.12 -B scripts/source_manager.py verify
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

基线版本 2 记录已确认来源的 SHA-256、路径及辅助大小；当前无真实来源，sources 为空。apply 不更新基线；新来源显示 baseline_pending，只有单独 `baseline-update --apply` 才补充锚点。更新前必须通过全部原件、清单和已有锚点检查，不允许改写旧哈希来掩盖异常。

发现原件被修改、丢失、未登记文件、清单异常或哈希冲突时，停止后续写入，保留现场并人工检查可信备份与历史。禁止删除或重建基线消除报错。原件已发布而清单失败时，保留原件并报告异常；本阶段不实现自动修复。暂存锁或异常临时文件也不得擅自清理。

## 后续路线（每阶段开始前确认）

1. Phase 1（本阶段）：Obsidian 学习数据结构、笔记模板、双链规范与只读验证；不导入资料。
2. Phase 2A（本阶段）：安全导入基础设施与 SHA-256 来源清单；Phase 2B（未开始）：正文解析、页码映射与人工审核。
3. Phase 3：本地检索与来源追溯。
4. Phase 4：多模型适配、带来源和页码的知识问答。
5. Phase 5：错题、复习记录和阶段测评流程。
6. Phase 6：薄弱点分析、长期维护、备份和恢复验证。

## 安全注意事项

所有层级的 `.obsidian/` 目录及其内容均保留在本地，不进入 Git，不因忽略规则而删除或移动。

Phase 1 的路径/大小/时间基线已在原件区为空且旧验证通过时升级。当前使用 SHA-256 判断内容一致性，大小和时间不能替代它。SHA-256 不是数字签名，不抵御有权限同时篡改原件、清单和基线的人，不能宣称为强防篡改机制；保留可信 Git 历史和独立备份仍有必要。Windows ACL 尚未启用。

遵守 `AGENTS.md`。任何删除必须明确确认，普通删除默认归档；原件永不删除。禁止未经确认的批量资料操作。创建文件不得覆盖同名文件；编辑前检查 Git 状态。API Key 仅由环境变量提供，不写入任何笔记、样例或日志。`.env.example` 只能保留空值。配置中的 `api_key_env` 仅引用变量名称。

`.gitignore` 排除原件、敏感文件、日志、缓存、测试沙箱及全部 Obsidian 配置，但不能阻止强制添加，也不能移除已跟踪文件。来源清单、代码和正式笔记可以跟踪。写入仅限项目内，拒绝链接、目录联接、路径穿越和项目外路径；并发锁只保护本工具，不替代操作系统权限。工具不持久化运行日志，错误仅输出固定代码，不输出正文、密钥或底层异常的绝对路径。不得擅自提交；Phase 2A 完成后等待用户检查，不开始 Phase 2B。
