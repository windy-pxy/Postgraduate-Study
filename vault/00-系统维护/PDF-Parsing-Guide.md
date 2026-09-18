# 本地 PDF 解析与质量审核指南（Phase 2B）

Phase 2B 把一份已经安全导入、登记并通过 SHA-256 校验的数字原生 PDF，转换成逐页、可审阅的 Markdown 派生产物。自动测试 PDF 由测试程序在项目内临时生成；已授权的真实来源必须遵守同样的只读、追溯和审核规则。

## 当前支持与明确不支持

当前只支持 PDF 中已有文字层的基础文本提取、页数与页码映射、图片存在性检测，以及必要的整页 PNG 预览。输入只能是来源清单中 `file_type: pdf` 的 source_id。工具不接受原始路径，也不会修改或复制原件。

当前不支持扫描版 OCR、复杂版面还原、表格语义、图表理解、数学公式转 LaTeX、页眉页脚智能删除、标题结构自动定稿、PPTX/DOCX 解析、AI 分类或云端服务。加密且需要密码的 PDF 会被拒绝。

## 为什么公式不能盲目转成 LaTeX

普通 PDF 文本提取会丢失二维排版、上下标、分式、根号范围、矩阵边界和符号字体映射。看起来相近的字符可能具有不同数学含义。错误公式比缺失公式更危险，会污染检索和后续知识笔记。

因此工具只用保守启发式标记 `needs_formula_review`。检测到数学符号、类似等式的文本或图片时，记录原始页码、不确定原因，并生成整页预览；不会生成任何未核对的 LaTeX。页面正文放在 Markdown 文本围栏中忠实保留，不删除、替换或改写原文字符。

## 命令与 dry-run

在项目根目录运行；`<source_id>` 是占位符，只能替换为已登记 ID：

```powershell
py -3.12 -B scripts/pdf_parser.py inspect <source_id>
py -3.12 -B scripts/pdf_parser.py parse <source_id>
py -3.12 -B scripts/pdf_parser.py parse <source_id> --apply
py -3.12 -B scripts/pdf_parser.py verify-output <source_id>
py -3.12 -B scripts/pdf_parser.py report <source_id>
```

`inspect`、`verify-output`、`report` 只读。`parse` 默认只显示计划；只有明确 `--apply` 才创建输出。解析前先运行完整来源校验并重算目标原件哈希，解析结束、发布前再次核对哈希。目标目录已经存在时拒绝覆盖、合并或重跑。

## 输出目录

每份来源固定写入：

```text
vault/90-Parsed-Sources/<source_id>/
├─ index.md
├─ pages/
│  ├─ page-0001.md
│  └─ ...
├─ assets/
│  ├─ page-0001.png   # 仅在需要预览时生成
│  └─ ...
├─ parse-report.json
└─ review.md
```

`index.md` 记录来源 ID、原始文件名、分类、解析器版本、页数与解析时间，并链接所有页面。每页顶部保存 source_id、从 1 开始的原始页码、提取状态、图片数、公式复核标记，以及可能的页面预览路径。

`review.md` 是人工核对清单。所有文件都属于 derived，初始状态只能是 review_required；它们不能自动进入知识笔记、错题或真题目录。正式笔记应在人工核对来源、页码和语义后另行建立，并链接来源，而不是直接把机器提取文本改名冒充知识。

解析先写入 `90-Parsed-Sources` 下本次专属的隐藏临时目录，结构和质量检查通过后才原子发布。发布成功后，工具用同目录临时文件和原子替换，仅将对应来源 manifest 的 parser 字段更新为 `parsed`、解析器名称/版本、页数、带时区的时间、项目内输出路径和 `review_required`；来源身份、哈希、分类与导入信息保持不变。失败只清理本次创建且身份一致的临时目录，不碰既有解析目录。

## 如何阅读质量报告

`parse-report.json` 使用稳定 JSON，重点字段如下：

- `declared_page_count` / `output_page_count`：PDF 页数与生成页面数，必须一致。
- `total_character_count`：各页原始提取字符数合计，仅作质量线索。
- `empty_pages`：没有提取到可见文本的页，可能是真空白、图片页或扫描页。
- `error_pages`：文本提取发生异常的页；仍会生成对应页面，不会静默跳过。
- `image_pages` / `image_count`：检测到嵌入图片的页和数量。
- `formula_review_pages`：需要人工检查公式或复杂图形的页。
- `quality_warnings`：空页、图片、提取失败或预览失败等固定警告。
- `pages`：逐页状态、字符数、图片数、预览资源和错误代码。

`verify-output` 会重算这些指标，并核对当前原件 SHA-256、PDF 当前页数、页面文件全集、逐页 frontmatter、PNG 签名、内部链接和 review_required 状态。它也拒绝项目外链接、额外页面和常见敏感模式。验证通过只表示结构自洽，不能证明文字、顺序或公式含义准确。

正文不做自动脱敏，因为派生资料必须忠实反映原文。如果检测到高置信疑似真实密钥，整份解析会在发布前停止；终端、待审核报告和异常都不包含疑似密钥原文，只记录 `SENSITIVE_CONTENT_BLOCKED`、页码和风险类型。安全报告位于 `review-queue/pdf-parse-blocks/<source_id>.json`，manifest 保持 `not_started`，正式派生目录不会生成。`YOUR_API_KEY`、环境变量占位符和普通教材代码示例保持原样。

## 首次真实验证建议

人工批准首次真实测试时，选择自己有权使用的、2～5 页、无密码、文字可选中的简单 PDF。页面宜包含一页普通中文段落、一页简单英文或数字、一页普通插图；避开个人隐私、密钥、复杂公式、双栏排版、扫描页、表格和大尺寸图片。

先完成 Phase 2A 导入与基线确认，再运行 inspect 和 parse dry-run；确认 source_id、页数和目标目录后才考虑 `--apply`。解析后依次运行 verify-output、report 和人工逐页对照。发现乱码、空页、页序错误或公式问题时停止，不要用猜测修补或直接转入正式知识笔记。

## 已知限制

PyMuPDF 的基础文本顺序由 PDF 内部对象与坐标决定，复杂多栏版面可能乱序；字体编码可能导致中文或符号乱码；图片检测不等于理解图片。整页预览只在空页、异常页、含图片或疑似公式/图形时生成，当前不做区域裁剪。

对质量路由标记为 `enhanced_parse_queued` 的页面，可以运行 PaddleOCR-VL 单页增强器。它生成独立候选，不能回写本页基础文本；即使替换字符减少或生成了 LaTeX，也不等于数学含义正确。MinerU 仅保留作诊断对照。详见 [[00-系统维护/Enhanced-Parsing-Guide|本地公式增强解析指南]]。

解析产物目录与来源 manifest 不是一个整体原子事务。工具先发布已验证的目录，再原子更新 manifest；极端中断可能留下“目录已存在但 manifest 仍是 not_started”。反向的目录缺失、manifest 与报告页数/解析器/时间不一致也会被验证器报错。保留现场并人工检查，不得删除既有输出、手改 manifest 或盲目重跑。目标目录存在时始终拒绝重复解析。

## Phase 2C 页面路由

Phase 2B 结果是不可覆盖的基础候选。Phase 2C 使用 `parsing-profiles.yaml` 按页检查替换字符、上下标、公式、表格、多栏、阅读顺序和编码风险。正常页保留基础候选，异常页进入未来增强队列；任何增强结果都单独保存并保持 `review_required`。完整设计见 [[00-系统维护/Scalable-Parsing-Architecture|可扩展解析架构]]。

[[学习主页|返回首页]] · [[00-系统维护/Source-Import-Guide|安全导入指南]] · [[00-系统维护/Validation-Guide|统一验证说明]]
