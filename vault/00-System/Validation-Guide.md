# 只读验证说明

在项目根目录 PowerShell 执行：

```powershell
py -3.12 -B scripts/health_check.py
py -3.12 -B scripts/validate_vault.py
py -3.12 -B scripts/source_manager.py verify
py -3.12 -B scripts/pdf_parser.py --help
py -3.12 -B scripts/parsing_architecture.py validate-config
py -3.12 -B scripts/parsing_architecture.py verify-plan <source_id>
py -3.12 -B scripts/enhanced_parser.py model-status
py -3.12 -B scripts/local_search.py verify
py -3.12 -B -m unittest discover -s tests -v
```

验证器使用本机已安装的 PyYAML 6.0.3，不联网、不安装依赖。迁移环境若缺少 PyYAML，会提示并退出，不会自行安装。`-B` 避免写入 Python 字节码缓存。

## 检查范围

- YAML 使用安全加载器：检查语法、顶层映射、重复键，拒绝危险对象构造和递归引用。
- 正式笔记检查全部通用字段、枚举、掌握程度、日期和页码格式，检测重复 id、未替换占位符。
- source-note 检查原始来源路径及文件是否存在；mistake 检查固定错误类型。
- 只豁免明确登记的系统/导航文件和七个模板中的合法占位符，未知位置的普通笔记不能靠省略 YAML 绕过检查。
- 检查正文和 YAML 内部双链的文件目标，包括别名、嵌入；忽略代码示例和 HTML 注释。目标重名时要求明确路径。
- 跳过 vault 内的隐藏设备配置，不读取 .obsidian 配置、.env 或 API Key。读取 Markdown 是验证所必需，但错误报告不输出原文或字段值。
- 扫描前拒绝符号链接、目录联接与其他重解析点，禁止通过链接越界。程序只读，不自动修复或创建文件。
- `90-Parsed-Sources/src-*` 下的 Markdown 由 PDF 专用验证器检查，不按正式知识笔记模板误判；Vault 总验证会逐个调用 `verify-output`，检查派生目录结构、页码、资源、报告、来源完整性以及 manifest 的 parsed 状态。
- Phase 2C 校验三种解析档案、禁用云端适配器、项目内模型缓存、单并发、单页重试和断点规则。路由计划不包含正文，不改写已有解析页。
- Phase 2D-0 校验批次上限、筛选条件、资源估算、队列去重、断点恢复和单页重试。计划命令必须保持 `would_parse: false`，无筛选的全库计划需要显式确认。
- 本地增强验证会检查已登记来源、逐页路由、关键模型 SHA-256、新候选目录文件全集、来源页码、原件哈希和 `review_required`。它验证可追溯结构，不能证明 LaTeX 或数学语义正确。
- 本地检索验证会检查来源完整性、SQLite 元数据、FTS 行数、来源/内容哈希、项目内相对路径和版本审核状态。索引验证通过表示快照一致，不表示片段或公式已经人工判定正确。

## 原始资料基线

`config/sources-original.baseline.json` 已从 Phase 1 元数据快照升级为版本 2 的 SHA-256 身份锚点。来源清单位于 `config/source-manifests/`，每份原件保存完整 SHA-256。健康检查与 Vault 验证均调用同一只读校验逻辑，流式读取原件二进制计算哈希，不解析或输出正文。

真实基线和来源清单只保留本地并被 Git 忽略；可提交的 `config/sources-original.baseline.example.json` 仅为空结构说明。健康检查仍要求真实基线在本地存在，并会拒绝 Git 跟踪真实基线、真实 manifest、计划、解析产物或运行状态。代码和样例不能恢复丢失的动态资料，因此这些本地数据需要单独备份。

校验检测被修改/缺失原件、未登记原件、缺失/无效清单、同一哈希的冲突记录及清单与既有基线冲突。名称、大小、时间不能替代 SHA-256；单纯时间变化不会改变来源身份。verify 不更新记录，apply 仅新增原件和清单，新来源列为 baseline_pending；人工确认后才可单独 `baseline-update --apply` 补充锚点，存在完整性异常时拒绝。

禁止删除、重建或改空基线来掩盖异常。SHA-256 并非数字签名或实时监控，不能抵御同时改动文件与校验记录的有权限者。Windows ACL 尚未启用；Windows 只读属性也不是强安全边界。验证时请避免其他程序并发修改资料。异常处理与已知限制见 [[00-System/Source-Import-Guide|安全导入指南]]。

## 错误与处置

退出码 0：检查通过；1：校验失败；2：缺少 PyYAML。失败时只列路径、错误码及必要字段名，不回显敏感内容。常见代码：

| 错误码 | 含义 |
| --- | --- |
| YAML_INVALID | YAML 格式错误、重复键或递归结构 |
| FRONTMATTER_REQUIRED / FIELD_REQUIRED | 正式笔记缺少 YAML 或必需字段 |
| ID_INVALID / ID_DUPLICATE | id 缺失、格式错误或重复 |
| TYPE_INVALID / COURSE_INVALID / SUBJECT_INVALID | 类型或课程学科不符合规范 |
| MASTERY_INVALID / DATE_INVALID / PAGE_INVALID | 掌握程度、日期或页码错误 |
| LINK_MISSING_OR_AMBIGUOUS | 双链目标缺失、越界或短标题重名 |
| UNRESOLVED_PLACEHOLDER | 正式笔记仍有模板占位符 |
| SOURCE_CITATION_REQUIRED / SOURCE_FILE_MISSING | 资料笔记缺来源记录或文件 |
| HASH_MISMATCH / UNREGISTERED_ORIGINAL | 原件哈希改变或存在未登记原件 |
| BASELINE_CONFLICT / BASELINE_SOURCE_MISSING | 清单与已有身份锚点冲突或缺失 |
| SOURCE_INTEGRITY_CHECK_FAILED | 来源清单、路径或基线结构无法安全校验 |
| PARSE_STATE_CONFLICT / PARSED_OUTPUT_MISSING | 派生目录与 manifest 的 not_started/parsed 状态不一致 |
| PARSE_MANIFEST_REPORT_CONFLICT | manifest 与解析报告的来源、解析器、时间或页数不一致 |
| SENSITIVE_CONTENT_BLOCKED | 高置信疑似密钥阻止派生产物发布，错误输出不含原文 |
| PARSED_OUTPUT_INVALID / UNREGISTERED_PARSED_OUTPUT | 派生 PDF 输出结构不完整或出现未登记目录/文件 |
| UNSAFE_PATH_OR_UNREADABLE_INPUT | 路径不安全或输入不可读 |

每次运行由人工按报错逐项检查；验证器不修改笔记，不删除、不移动资料。通过验证仅表示结构满足规则，不能保证页码、答案、语义关系真实。

[[00-System/Home|返回首页]] · [[00-System/Review-Queue|待审核列表]]
