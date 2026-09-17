# 人工审核与接受指南

本流程把“待审核候选”转成可供正式检索的不可覆盖快照。接受表示审核人已对照原页确认该页可用于检索，不表示题目答案或教材观点已经得到独立证明。

## 三层数据

- 候选：basic、enhanced 或人工校正稿，状态保持 `review_required`。
- 接受快照：位于 `90-Parsed-Sources/<source_id>/accepted/pages/page-XXXX/<acceptance_id>.md`，创建后不得覆盖。
- 审核事件：本地保存在 `review-queue/acceptance-events/`，记录来源哈希、候选哈希、快照哈希、审核人、时间和说明；真实事件不进入 Git。

正式索引只信任同时满足以下条件的页面：原件 SHA-256 正常、候选内容哈希未改变、接受快照哈希正常、存在有效接受事件且没有后续撤销事件。单独创建带 `review_status: accepted` 的 Markdown 不会进入正式索引。

## 审核步骤

先检查一页。该命令只输出路径、解析器和哈希，不输出整页正文：

```powershell
py -3.12 -B scripts/review_manager.py inspect --source-id <source_id> --page <PDF物理页码>
```

在 Obsidian 中并排打开 `page_preview_relative_path`、basic、enhanced 和人工校正候选。至少核对：

- 题干、选项和顺序完整；
- 负号、上下标、不等号、补码等关键符号准确；
- 图表和题目对应正确；
- 没有漏题干、跨题粘连或模型推断补写；
- 页码使用从 1 开始的 PDF 物理页码。

接受命令默认只是预演：

```powershell
py -3.12 -B scripts/review_manager.py accept `
  --source-id <source_id> `
  --page <PDF物理页码> `
  --candidate <项目内候选相对路径> `
  --reviewer "<审核人标识>" `
  --notes "<核对范围和结论>"
```

确认预演中的来源、页码、候选哈希和目标路径后，只有显式增加 `--apply` 才会新建快照及接受事件。工具不覆盖同名文件，也不会改写候选和原件。

接受后显式重建索引：

```powershell
py -3.12 -B scripts/review_manager.py verify
py -3.12 -B scripts/local_search.py build --include-review-candidates --rebuild
py -3.12 -B scripts/local_search.py verify
```

索引记录审核事件 ID。接受状态变化后，旧索引会拒绝查询并要求重建，避免未完成或已撤销的内容继续出现在正式问答中。

## 撤销

撤销同样默认预演，必须指定接受事件 ID、审核人和原因：

```powershell
py -3.12 -B scripts/review_manager.py revoke `
  --acceptance-id <acc-...> `
  --reviewer "<审核人标识>" `
  --reason "<撤销原因>"
```

确认后增加 `--apply`。撤销只追加事件，不删除、不移动、不覆盖接受快照。随后重新运行审核验证并重建索引；撤销页面将不再被正式查询命中，历史仍可审计。

## 状态与异常

```powershell
py -3.12 -B scripts/review_manager.py status
py -3.12 -B scripts/review_manager.py verify
```

`status` 显示待审核候选数、当前有效接受数、已撤销数和完整性异常数。候选、快照或事件被改动，出现未登记快照、同页多个有效接受、来源异常或中断状态时，`verify` 失败，正式索引不得重建。

审核人字段只是本地可追溯标识，不是密码学签名。SHA-256 用于检测内容变化，也不能证明审核人身份。审核事件、接受快照和索引需要随本地动态资料一起备份。

[[00-系统维护/Local-Retrieval-Guide|本地页级检索指南]] · [[00-系统维护/Claudian-Study-Pilot-Guide|Claudian 试点指南]] · [[学习主页|首页]]
