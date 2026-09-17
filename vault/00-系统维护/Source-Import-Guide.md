# 安全资料导入指南（Phase 2A）

Phase 2A 导入基础设施已验收并提交；当前 Phase 2B 已建立数字原生 PDF 的本地解析框架，但仍未导入真实学习资料。导入系统只识别格式、计算 SHA-256、复制原件和登记来源；解析由独立工具处理，说明见 [[00-系统维护/PDF-Parsing-Guide|PDF 解析指南]]。

## 先理解三个位置

- `import-inbox/`：你投放新资料的入口。默认复制，成功后这里的文件仍然保留，不自动移动或删除。
- `sources-original/`：导入后的原件区。只允许导入工具新建一份原件，不覆盖、不编辑、不删除已有原件。
- `config/source-manifests/`：每份原件对应一个 JSON 来源清单，记录身份、路径、分类和完整 SHA-256，不保存正文。

以上均是项目相对路径，项目根目录是 `D:\Postgraduate-Study`。来源清单和代码可以进入 Git；原始 PDF、PPTX、DOCX 继续被忽略。原件本身需要你另行安排可信备份，Git 不备份资料正文。

## 支持哪些格式

只正式支持 `.pdf`、`.pptx`、`.docx`，扩展名大小写均可。PDF 检查 `%PDF-` 文件头；Office 检查 ZIP 容器目录、内容类型声明、根关系和相应主部件是否存在。它不解码正文，也不保证整篇 PDF 可渲染或 Office 正文 XML 语义正确。损坏的 ZIP 元数据、类型不匹配或危险容器结构会被拒绝。

`.ppt`、`.doc`、图片、压缩包、文本等标为 unsupported，不自动转换。只改扩展名不能变成受支持文件。不安装 OCR、插件或新依赖，不访问网络。

## 分类必须自己确认

| course | subject（导入系统使用小写） |
| --- | --- |
| math1 | calculus、linear-algebra、probability |
| 408 | data-structure、computer-organization、operating-system、computer-network |

source_type 只能是 textbook、wangdao、zhangyu、teacher-ppt、past-paper、exercise、notes、other。不要根据资料文件名猜测版本、科目或类别。当前工具不实现自动分类；缺少分类时保存为待审核计划，suggested 字段为空并标注未推断，不会成为正式来源分类。

注意：Phase 1 笔记的 subject 使用 Calculus 等首字母大写标识；本阶段导入清单按上表使用小写。两套字段属于不同数据对象，暂不自动转换或生成笔记。

## 以后导入一份资料的步骤

在项目根目录打开 PowerShell。下方 `<待导入文件.pdf>`、`<计划ID>` 均为占位符，必须替换；分类值也必须依据实际资料选择，不要直接照抄。

1. 将自己确认的一份资料放入 import-inbox；先查看扫描结果。

   ```powershell
   py -3.12 -B scripts/source_manager.py scan
   ```

2. 预览单文件计划。未提供分类也可以预览，但不能导入。下面分类仅演示参数写法。

   ```powershell
   py -3.12 -B scripts/source_manager.py plan "import-inbox/<待导入文件.pdf>" --course math1 --subject calculus --source-type textbook
   ```

3. 核实分类后，增加 `--save` 将计划写入 `review-queue/import-plans/`。这个步骤只写审核计划，不复制原件。输出中的 plan_path 是下一步应使用的准确路径。

   ```powershell
   py -3.12 -B scripts/source_manager.py plan "import-inbox/<待导入文件.pdf>" --course math1 --subject calculus --source-type textbook --save
   ```

4. 先预演已保存计划，再明确执行。`apply` 子命令本身仍默认 dry-run；只有加 `--apply` 才会复制并登记。

   ```powershell
   py -3.12 -B scripts/source_manager.py apply --plan "review-queue/import-plans/<计划ID>.json"
   py -3.12 -B scripts/source_manager.py apply --plan "review-queue/import-plans/<计划ID>.json" --apply
   ```

   缺分类时请重新提供完整参数生成新计划，旧计划不会被改写。计划表示当时的审核快照；成功导入后也保留原样，不自动清理。status 通过已登记 SHA-256 判断哪些计划已完成。若 inbox 内容发生变化，原计划失效；先核实变化，再重新生成计划，不修改哈希字段骗过验证。

5. 检查完整性，再单独更新基线。apply 不自动更新基线；清单已经保存完整 SHA-256，新来源会列在 baseline_pending。只有确认这些确为刚导入的资料后，才执行明确更新。

   ```powershell
   py -3.12 -B scripts/source_manager.py verify
   py -3.12 -B scripts/source_manager.py baseline-update
   py -3.12 -B scripts/source_manager.py baseline-update --apply
   ```

   更新命令先比较已有基线、来源清单与实际文件；任一旧记录冲突、原件变更、文件丢失或未登记原件都会阻止更新。它只能保留旧身份锚点并补充新来源，不能合法化修改后的原件。基线不是临时缓存，禁止删除、改空或重建来消除异常。

6. 查看清单和总状态。

   ```powershell
   py -3.12 -B scripts/source_manager.py list
   py -3.12 -B scripts/source_manager.py status
   py -3.12 -B scripts/source_manager.py --help
   ```

每个子命令也支持 `--help`。无需执行复杂 Python 模块路径；也可省略 `-B`，但建议保留以避免 Python 缓存。

## 身份、清单与复制保护

source_id 默认为 `src-` 加 SHA-256 前 12 位；完整哈希存入清单。同一内容改名仍是同一来源，重复内容不会再次导入；遇到前缀冲突，会逐位延长新 ID，保留既有 ID。同名不同内容使用不同 ID，不会互相覆盖。

保存路径为 `sources-original/<course>/<subject>/<source_id>/<安全文件名>`。复制前拒绝既有 source_id 目录或文件；文件名会去除危险字符。路径必须位于项目内，符号链接、目录联接、其他重解析点、硬链接、绝对路径、上级目录穿越和 Windows ADS 被拒绝。

工具先将原件复制为目标目录内的独占临时文件，刷盘后重算 SHA-256，再与计划及 inbox 比较。成功后使用不覆盖目标的原子发布；清单也采用同目录临时文件和原子发布。失败只清理本次创建且身份相符的临时文件和空目录，绝不删除既有用户文件或已经正式落盘的原件。

清单字段包括 schema_version、source_id、sha256、original_filename、stored_relative_path、file_type、size_bytes、course、subject、source_type、classification_status、import_status、imported_at，以及 parser_status/name/version、page_count、parsed_at、parsed_output_relative_path、parse_review_status、notes。JSON 稳定排序、UTF-8，不保存绝对用户目录或资料正文。真实清单属于本地学习数据，不进入 Git。

刚导入时 `parser_status` 为 `not_started`，六个解析字段为空。PDF 解析器只在原件哈希通过、临时产物验证通过且输出目录原子发布后，才原子更新这些字段为 `parsed`、解析器名称/版本、页数、带时区的解析时间、项目内派生目录和 `review_required`。该更新不改写原有来源身份、哈希、分类或导入信息。

## 原件异常怎么办

发现 HASH_MISMATCH、UNREGISTERED_ORIGINAL、缺失原件、缺失清单或 BASELINE_CONFLICT 时，先停止导入，保留现场并人工检查文件、清单和可信备份。不要编辑原件、自动移动文件、删除可疑文件或重建基线。恢复操作需要另行明确授权；本阶段不提供自动修复命令。

原件和来源清单是两个文件，不能整体原子提交。如果原件已经发布、清单写入失败，工具保留原件，verify 报未登记原件，并阻止后续写入。此时需要人工依据保留的计划和校验结果处理，不能重新 apply 覆盖它。进程意外中断也可能留下锁或临时文件，工具不会擅自清理；请先确认没有其他导入任务，再另行授权处理。

PDF 派生目录与 manifest 更新也不能组成一个整体原子事务。已有派生目录但 manifest 仍是 `not_started`，或 manifest 是 `parsed` 但目录缺失、页数/报告不一致，`verify` 都会报错。保留现场人工检查，不要删除目录、手改状态或重新解析来掩盖中断。

## 安全边界与局限

SHA-256 是判断内容是否一致的权威依据，文件名、大小和修改时间不是替代品；改回时间戳或保持同样大小无法绕过哈希比较。基线版本 2 保存已确认的来源哈希与路径；Phase 1 的元数据基线已经在原始区为空时升级，不存在真实资料的重新登记。

SHA-256 不是数字签名，也不能抵御有权限同时篡改原件、清单和基线的人。应保留可信 Git 历史与独立备份；清单仅新建，基线仅在明确命令且现状无异常时更新。verify、scan、list、status 均只读，不自动修改这些记录。list 只读取来源元数据；verify/scan 会流式读取二进制用于签名与哈希，不解析正文。

真实 manifest、真实基线、导入计划和解析产物只保留本地并被 Git 忽略。仓库中的 `config/sources-original.baseline.example.json` 只说明空结构，不含真实 source_id、哈希、文件名、路径或时间；它不能替代真实基线，也不能作为动态学习资料的备份。

Windows ACL 尚未设置。本工具也不自动设置 Windows 只读属性；即使以后设置，只读属性也可被有权限的用户撤销，不是强安全边界。操作锁可阻止本工具并发写入，但不是对抗其他恶意进程的隔离机制；导入时不要并发修改相关目录。

本阶段不持久化审计日志。命令输出仅含相对路径、分类、ID、校验摘要和固定错误码，不输出正文、API Key 或底层异常中的绝对目录。建议不要把敏感信息写进文件名。合成测试只在项目内 tests/.runtime 运行并清理自己的临时目录，不修改实际 sources-original。Phase 2B 解析器同样按 source_id 工作，不接受项目外路径；其产物与正式笔记分开。

来源完成基础解析后，Phase 2C 再由人工依资料类型选择 `math1_formula_dense`、`cs408_general` 或 `cs408_symbol_dense`。档案不改动导入分类和原件，只生成页面质量路由计划。增强候选和人工注释不得回写基础产物。

路由为 `enhanced_parse_queued` 的页可使用 MinerU 本地单页增强器；它仍然只读原件，并写入独立的待审核候选目录。导入、基础解析和增强候选是三个不同步骤，增强成功不会改变来源身份、哈希或基础解析 manifest。详见 [[00-系统维护/Enhanced-Parsing-Guide|本地公式增强解析指南]]。

[[学习主页|返回首页]] · [[00-系统维护/Validation-Guide|统一验证说明]]
