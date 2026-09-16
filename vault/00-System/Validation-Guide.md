# 只读验证说明

在项目根目录 PowerShell 执行：

```powershell
py -3.12 -B scripts/health_check.py
py -3.12 -B scripts/validate_vault.py
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

## 原始资料基线

`config/sources-original.baseline.json` 保存 Phase 1 开始时原始目录的路径、文件大小和修改时间。当前原始区只有两个空 .gitkeep。每次运行比较目录清单及元数据，可发现新增、缺失、改名或元数据变化；不读取原始资料内容、不更新基线。

新增资料也会触发 ORIGINAL_INVENTORY_CHANGED。本阶段不应出现任何新增原件或生成物。未来用户授权导入阶段才可以审阅并更新基线，不能为了清除报错自行重置它。换电脑或重新检出 Git 可能改变文件时间，须人工确认后另行授权更新基线。

元数据基线不是内容哈希或实时监控，不能证明从未发生过写入；同尺寸且时间被还原的变更无法据此识别。程序不设置 ACL，不代替备份或操作系统只读权限。运行验证时请避免其他程序同时修改资料。

当前基线不得描述为强防篡改。**Phase 2 导入真实资料前，必须先升级为 SHA-256 内容哈希校验。** Windows ACL 尚未启用；本阶段仅补充说明，不实现 Phase 2 导入或哈希升级，也不修改现有基线。

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
| ORIGINAL_INVENTORY_CHANGED | 原始目录与只读基线不一致 |
| UNSAFE_PATH_OR_UNREADABLE_INPUT | 路径不安全或输入不可读 |

每次运行由人工按报错逐项检查；验证器不修改笔记，不删除、不移动资料。通过验证仅表示结构满足规则，不能保证页码、答案、语义关系真实。

[[00-System/Home|返回首页]] · [[00-System/Review-Queue|待审核列表]]
