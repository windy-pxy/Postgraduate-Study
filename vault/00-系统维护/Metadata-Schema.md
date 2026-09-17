# 元数据规范

本页是系统说明，不是正式学习笔记。仅有七类正式笔记：knowledge、mistake、past-paper、source-note、stage-test、study-record、weakness。导航和本规范不伪装成知识点。

## 存储约定

知识点放在各学科目录或 `03-知识笔记`；错题、真题、测试、薄弱点、学习记录分别放在对应中文编号目录。资料笔记放在 `90-Parsed-Sources`，它们是可核对的派生笔记，绝不是原件。所有 Markdown 使用 UTF-8，正式笔记以 `---` 包围 YAML frontmatter。

每篇笔记只归属一个 course；跨数学一和 408 的记录拆成笔记后建立有意义的关联。文件名可以用中文，字段名用英文。不要根据标题判断身份；id 是长期身份标识，重命名文件或调整目录时保留 id。

## 通用字段（必须保留字段名）

| 字段 | 类型与要求 |
| --- | --- |
| id | 非空唯一字符串；推荐 `note-` 加 UUID。允许 8～128 位英文字母、数字、下划线、连字符，首位须为字母或数字。模板保留 `"{{id}}"`，新笔记不得复用模板或其他笔记的 id。 |
| type | 固定枚举：knowledge、mistake、past-paper、source-note、stage-test、study-record、weakness。 |
| course | 字符串 `"math1"` 或 `"408"`；408 必须加引号，避免被 YAML 当成整数。 |
| subject | 使用下表中的学科标识，与 course 匹配。 |
| chapter | 字符串或空值；按真实资料章节填写，可写带引号的章节页双链，不猜测章号。 |
| knowledge_points | 列表，元素为带引号的 Obsidian 双链；暂时没有已核实知识点时用 `[]`。 |
| source_type | 字符串或空值；建议 textbook、wangdao、zhangyu、ppt、past-paper、self、other；这是建议词汇，不是强制枚举。 |
| source_name | 资料真实名称及必要版次；无来源留空。 |
| source_page | 原始资料印刷页码或幻灯片页号；无来源或未确认留空，不得编造。推荐带引号的字符串。 |
| difficulty | 有依据时填 1～5 的整数，未知留空；不能用 0 或猜测分数。 |
| mastery | 必填整数 0～5，只能由真实自评或证据决定。 |
| status | draft（草稿）、active（使用中）、reviewed（已核对）、archived（归档状态）；状态更改不自动移动文件。 |
| created | 创建日期，YYYY-MM-DD，推荐加引号。 |
| updated | 最近实质更新日期，YYYY-MM-DD，不得早于 created。 |
| review_dates | 已发生的复习日期列表，YYYY-MM-DD；没有记录用 `[]`，计划写在正文。 |
| tags | 字符串列表，无标签用 `[]`；不要用标签制造虚构分类。 |

| course | subject |
| --- | --- |
| math1 | Calculus、Linear-Algebra、Probability |
| 408 | Data-Structure、Computer-Organization、Operating-System、Computer-Network |

掌握程度固定为：0 完全不会；1 仅见过；2 理解不完整；3 能完成基础题；4 能够稳定解题；5 能够讲解和迁移。模板不默认填 0，避免把未知当成完全不会。

## YAML 写法

双链值和模板占位符必须加引号；`knowledge_points` 使用块列表或 YAML 行内列表，不能直接把双链当成未加引号的 YAML 数组。模板已经提供合法语法。字段未知写成空值（冒号后不填）或空列表，而不是填“未知”冒充页码或日期。mastery、course、subject 等必填字段仍需填写后才能通过正式笔记检查。

模板只有 type 是确定的结构常量；其余数据用占位符。复制后手动替换占位符，不依赖任何插件自动生成字段。空章节可以保留标题，但必须清除正文未填的 `{{...}}`。正文的“我的理解”必须与有来源的摘录、结论分开。

## 来源与页码

source_page 支持正整数页码、闭区间、逗号分隔的页码或区间，也支持罗马页码与附录页标。数字范围不能倒序；不接受负数、零、浮点数、日期、对象或列表。格式说明中的数字只代表语法示意，不代表实际资料。

保留原件上的页码，不得用阅读器显示的文件页序号替换印刷页码。需要时在正文分别记录“原件页码”和“PDF 文件页序号”。对工具暂不支持的特殊页标，保留原始标记并进入人工审核，不得改造为猜测数字只为通过验证。验证只能发现明显格式错误，不能证明引文真实。

source-note 额外要求 `source_file`，值为以 `sources-original/math1/` 或 `sources-original/408/` 开头的项目相对文件路径。正式资料笔记必须提供真实 source_name、source_file、source_page；资料或页码未确认时先记到审核列表，不伪造一篇完整资料笔记。其他类型无来源允许 source_page 留空。

## 专用字段与正文数据

mistake 额外要求 `error_type`：concept、calculation、method、reading、memory、careless、unknown。主错误类型选一项，多重原因在正文解释；无法确定时用 unknown。

真题年份与题号、测试得分与满分、耗时、学习时长、薄弱点出现次数等记录在模板对应小节，本阶段无默认数值。得分需标明满分，时长统一说明分钟；再次做对记录“是／否／未复测”及真实日期，不能把未复测写成否。

## 来源 manifest 的解析状态

`config/source-manifests/<source_id>.json` 不是笔记 YAML，但是来源追溯的权威元数据。新导入来源的 `parser_status` 为 `not_started`，`parser_name`、`parser_version`、`page_count`、`parsed_at`、`parsed_output_relative_path`、`parse_review_status` 均为 null。

只有在原件 SHA-256 通过、解析产物验证通过并原子发布后，解析器才原子更新这六个字段：`parser_status: parsed`、实际解析器名称和版本、正整数页数、带时区 ISO 8601 的 `parsed_at`、精确的项目内相对路径 `vault/90-Parsed-Sources/<source_id>`，以及 `parse_review_status: review_required`。原有 source_id、SHA-256、文件名、存储路径、分类和导入时间不得改写。任何一边缺失或页数、报告不一致都必须由验证器报错。

## 豁免范围

仅验证器中明确列出的系统说明和导航页免填学习元数据；新建普通 Markdown（即使在 `00-系统维护` 或 `99-笔记模板` 内）仍按正式笔记检查。七个固定模板允许占位符，但仍检查 YAML、固定 type 和非占位符字段。代码块、行内代码中的双链写法示例不参与目标检查。

入口：[[学习主页|首页]] · [[00-系统维护/Linking-Rules|双链规范]] · [[00-系统维护/Validation-Guide|验证说明]]
