	# 数学一 + 408 学习首页

Phase 1、Phase 2A 和 Phase 2B 框架已完成；当前 Phase 2C-Architecture 建立页面质量路由、状态机和未来增强解析器接口。已有解析产物保持只读，模板与导航不代表已学习进度，正式笔记需填入真实记录后验证。

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
- [[00-System/Scalable-Parsing-Architecture|可扩展解析架构]]

## 仓库外部区域

以下目录位于 vault 外，使用项目相对路径说明，不创建失效双链：

- `sources-original/math1` 与 `sources-original/408`：原件永久只读。
- `import-inbox`：待确认的资料候选；导入必须遵循单文件计划和明确 apply。
- `review-queue`：后续候选产物审核区。
- `archive`：经明确确认后归档的非原始文件。
- `scripts`、`tests`、`config`、`prompts`、`logs`：工具、测试、配置样例、提示词与日志。

本阶段不安装插件或增强模型、不调用 API、不重解析已有 PDF，也不填入虚构知识、真题或成绩。
