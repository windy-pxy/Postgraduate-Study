# 数学一 + 408 Obsidian AI 考研学习系统

为未来 1～2 年的数学一与 408 学习建立本地、可迁移、可审阅的资料与笔记基础。最终运行不依赖 ChatGPT；后续计划通过适配器支持 DeepSeek、Claude、OpenAI 兼容 API 和本地模型。

## 当前阶段

Phase 0 已验收并完成首次提交。Phase 1 建立统一元数据、七类模板、导航与双链规范，以及只读验证工具；完成后等待人工检查，不自动提交。尚未实现解析、检索、问答、模型调用或自动学习分析，不安装任何 Obsidian 插件。

Phase 0 工具只用标准库；Phase 1 验证器使用本机已有的 PyYAML 6.0.3，本次不安装依赖。迁移后若缺少 PyYAML，工具会明确提示，不会自动安装。

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
py -3.12 -B -m unittest discover -s tests -v
git status --short
git diff --stat
```

本机 `python` 命令可能指向 Windows 应用执行别名，已采用 `py -3.12`。`-B` 避免生成 Python 缓存。测试使用内存模拟，不创建临时资料或访问项目外的用户文件。健康检查仅检查路径元数据与 Git 索引/状态，不读取学习资料、`.env` 内容或环境变量中的 Key；退出码 0 表示通过，1 表示发现问题。

## 后续路线（每阶段开始前确认）

1. Phase 1（本阶段）：Obsidian 学习数据结构、笔记模板、双链规范与只读验证；不导入资料。
2. Phase 2：小样本 PDF 等资料解析、页码映射与人工审核。
3. Phase 3：本地检索与来源追溯。
4. Phase 4：多模型适配、带来源和页码的知识问答。
5. Phase 5：错题、复习记录和阶段测评流程。
6. Phase 6：薄弱点分析、长期维护、备份和恢复验证。

## 安全注意事项

所有层级的 `.obsidian/` 目录及其内容均保留在本地，不进入 Git，不因忽略规则而删除或移动。

当前原件基线仅检查路径、大小和修改时间，不能称为强防篡改机制。**在 Phase 2 导入真实资料前，必须先将基线升级为 SHA-256 内容哈希校验。** 本阶段只记录这一前置要求，不实现导入程序或内容哈希升级。Windows ACL 尚未启用。

遵守 `AGENTS.md`。任何删除必须明确确认，普通删除默认归档；原件永不删除。禁止未经确认的批量资料操作。创建文件不得覆盖同名文件；编辑前检查 Git 状态。API Key 仅由环境变量提供，不写入任何笔记、样例或日志。`.env.example` 只能保留空值。配置中的 `api_key_env` 仅引用变量名称。

`.gitignore` 排除原件、敏感文件、日志、缓存和设备工作区状态，但不能阻止强制添加，也不能移除已跟踪文件。健康检查会检查索引中是否有真实环境文件、常见敏感文件或原件。它不是任意格式密钥泄露扫描器。未跟踪的原件保持本地，Git 不代替原始资料备份。当前未设置 Windows ACL，也未实现后续写入工具的强制路径保护；不得把书面规则误认为操作系统只读权限。Phase 1 验证器会拒绝扫描重解析点，并按 `config/sources-original.baseline.json` 检测原始目录清单、大小、修改时间变化；不读取原件内容，也不重置基线。跨机器检出可能改变时间戳，需要人工确认后另行授权更新基线。不得擅自提交；Phase 1 完成后等待用户检查，不继续下一阶段。
