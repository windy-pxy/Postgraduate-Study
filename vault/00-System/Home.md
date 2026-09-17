	# 数学一 + 408 学习首页

Phase 1 至本地增强与检索基础已完成；当前正在进行 Claudian + Codex 只读学习问答试点。基础结果保持只读，增强候选仍需人工审核；模板与导航不代表已学习进度，正式笔记需填入真实记录后验证。

## 学习区域

- [[01-Math1/Math1-MOC|数学一]]
- [[02-408/408-MOC|408]]
- [[03-Knowledge-Notes/Knowledge-MOC|知识笔记]]
- [[04-Mistakes/Mistakes-MOC|错题]]
- [[05-Past-Papers/Past-Papers-MOC|历年真题]]
- [[06-Stage-Tests/Stage-Tests-MOC|阶段测试]]
- [[07-Weakness-Analysis/Weakness-MOC|薄弱点分析]]
- [[08-Study-Records/Study-Records-MOC|学习记录]]
- [[80-Attachments/Attachments-MOC|附件]]
- [[90-Parsed-Sources/Parsed-Sources-MOC|资料笔记与解析产物]]
- [[99-Templates/Templates-MOC|七类笔记模板]]

## 系统规范

- [[00-System/Metadata-Schema|元数据规范]]
- [[00-System/Linking-Rules|双链规范]]
- [[00-System/Validation-Guide|验证工具与安全边界]]
- [[00-System/Review-Queue|待审核列表]]
- [[00-System/Source-Import-Guide|安全导入与 SHA-256 校验指南]]
- [[00-System/PDF-Parsing-Guide|本地 PDF 解析与质量审核指南]]
- [[00-System/Enhanced-Parsing-Guide|本地公式增强解析指南]]
- [[00-System/Local-Retrieval-Guide|本地页级检索指南]]
- [[00-System/Review-Acceptance-Guide|人工审核与接受指南]]
- [[00-System/Claudian-Study-Pilot-Guide|Claudian 只读学习问答试点]]
- [[00-System/Scalable-Parsing-Architecture|可扩展解析架构]]
- [[00-System/Batch-Parsing-Guide|大规模资料批次规划指南]]

## 仓库外部区域

以下目录位于 vault 外，使用项目相对路径说明，不创建失效双链：

- `sources-original/math1` 与 `sources-original/408`：原件永久只读。
- `import-inbox`：待确认的资料候选；导入必须遵循单文件计划和明确 apply。
- `review-queue`：后续候选产物审核区。
- `archive`：经明确确认后归档的非原始文件。
- `scripts`、`tests`、`config`、`prompts`、`logs`：工具、测试、配置样例、提示词与日志。

本地增强模型只在项目隔离环境中运行，不调用云端 API。Claudian 仅通过 Obsidian 官方社区插件渠道接入，并必须使用 Codex read-only 模式；系统不填入虚构知识、真题或成绩。
