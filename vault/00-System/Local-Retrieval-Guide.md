# 本地页级检索指南

本地检索只展示原始片段和来源定位，不调用大模型，也不生成答案。索引使用 Python 3.12 自带的 SQLite FTS5，支持中文关键词、source_id 和页码过滤，不需要向量模型或数据库服务。

## 审核边界

正式查询默认只返回经 Phase 3B 审核工具接受且尚未撤销的不可覆盖快照。每个快照必须关联有效接受事件，记录 source_id、完整来源 SHA-256、PDF 物理页码、候选哈希、实际解析器及版本，并标记 `review_status: "accepted"`。人工直接创建 accepted Markdown 或只修改 frontmatter 不会获得正式检索资格。

当前没有任何已接受页面，因此默认查询会返回 `暂无已审核资料`。这不是故障，也不能为了演示而自动放宽。

基础结果和增强候选只有在建库及查询时都显式指定 `--include-review-candidates` 才能预览。每条结果都带 `UNREVIEWED_CANDIDATE`、版本类型、解析器和页码；同页的 basic 与 enhanced 分成两条，不会无标识混合。

## 命令

在项目根目录执行：

```powershell
# 正式索引：只收录 accepted 页面
py -3.12 -B scripts/local_search.py build

# 审核期索引：同时收录待审核候选
py -3.12 -B scripts/local_search.py build --include-review-candidates --rebuild

py -3.12 -B scripts/local_search.py status
py -3.12 -B scripts/local_search.py verify

# 默认只查 accepted
py -3.12 -B scripts/local_search.py search "关键词"

# 明确预览待审核候选，并限制来源与原始页码
py -3.12 -B scripts/local_search.py search "关键词" --source-id <source_id> --page <页码> --include-review-candidates
```

索引位于 `indexes/local-search.sqlite3`，属于可重建的本地运行数据，不进入 Git。目标已存在时，`build` 会拒绝覆盖；只有明确 `--rebuild` 才用同目录临时数据库原子替换。`verify` 会重新检查原件完整性、接受与撤销事件、候选哈希、快照哈希、索引审核状态摘要、文档路径和内容哈希。接受或撤销后，旧索引立即拒绝查询，必须重建，不能继续使用陈旧结果。

## 结果字段

- `snippet`：命中位置附近的原始片段，不做摘要或改写。
- `source_id`、`source_sha256`、`page_number`：来源身份与原始页码。
- `version_kind`、`parser_id`、`parser_version`：区分 accepted、basic 和 enhanced。
- `review_status`、`risk`：说明能否作为正式检索内容。
- `acceptance_event_id`：accepted 结果对应的人工接受事件；候选结果为空。
- `source_pdf_relative_path`：原始 PDF 的项目内相对位置。
- `obsidian_wikilink`、`obsidian_uri`：定位 vault 中对应的页级文本版本。

Obsidian 链接定位的是可审核文本，`source_pdf_relative_path` 定位项目外的只读原件。检索不会改写原件、解析候选或知识笔记，也不会把命中片段扩写成结论。

接受、撤销和人工核对步骤见 [[00-System/Review-Acceptance-Guide|人工审核与接受指南]]。

入口：[[00-System/Enhanced-Parsing-Guide|本地公式增强解析指南]] · [[00-System/Validation-Guide|验证说明]] · [[00-System/Home|首页]]
