# 大规模资料批次规划指南

Phase 2D-0 只统计和规划未来任务，不调用 PDF 解析器，也不安装或调用 MinerU、Docling、OCR、云端 API。所有命令只接受已经导入并写入本地来源 manifest 的资料；`import-inbox` 中尚未确认的文件不会进入计划。

## 为什么分两步处理

数 GB 资料不能全部直接交给重型模型。先用 PyMuPDF 做数字原生 PDF 的基础解析，成本低、速度快；再根据逐页质量路由，只把替换字符、下标、公式、图片或编码异常页放进未来增强队列。质量正常页保留为基础候选，轻微异常页进入人工审核。这样能限制内存、显存和磁盘增长，也能让单页失败只影响该页。

当前默认配置适配 16 GB 内存和 RTX 4060 Laptop 8 GB 显存：并发数为 1，每个批次最多 25 页，增强任务不与普通批次并发。模型预算低于物理容量，仍只是估算值；真正安装增强解析器前必须用合成评估集重新测量。

## 查看来源和生成 dry-run 计划

```powershell
py -3.12 -B scripts/parsing_architecture.py source-status --course 408
py -3.12 -B scripts/parsing_architecture.py source-status --subject computer-organization
py -3.12 -B scripts/parsing_architecture.py batch-plan --course math1 --profile math1_formula_dense
py -3.12 -B scripts/parsing_architecture.py batch-plan --course 408 --source-type exercise
py -3.12 -B scripts/parsing_architecture.py estimate-resources --profile cs408_symbol_dense
```

可以用 `--course`、`--subject`、`--source-type`、`--profile` 或重复的 `--source-id` 缩小范围。`batch-plan` 默认只把 JSON 计划打印到终端，不写队列，不解析资料。需要保存计划时才加 `--save`；保存的仍是元数据计划，`would_parse` 固定为 `false`。不带任何筛选时必须明确加 `--confirm-all-sources`，该选项只确认查看全库规划，不授权重跑。

计划将项目分为：

- `basic`：尚待基础解析的来源，或已经通过基础质量门槛的页面；`requires_basic_parse` 表明是否真有待执行任务。
- `enhanced`：未来安装增强解析器后才可处理的异常页。
- `manual_review`：需要人工判断的页面或缺少质量路由的已解析来源。
- `resource_deferred`：文件大小等资源限制导致的推迟项。
- `already_queued`：相同来源和页码已在本地计划队列，避免重复排队。
- `unsupported`：当前阶段不支持的格式或高风险页面。

## 查看、暂停和恢复

```powershell
py -3.12 -B scripts/parsing_architecture.py queue-status
py -3.12 -B scripts/parsing_architecture.py resume-check --source-id <source_id>
```

Phase 2D-0 没有后台执行器，因此“暂停”只需不要启动后续解析阶段，也不要保存新的计划；不会有任务在后台继续运行。`queue-status` 只统计本地计划、单页重试和断点文件。`resume-check` 将断点分为 completed、failed 和 pending，后续执行器只能从最后一个已验证页面继续，不能借恢复操作触发整库重跑。

单页失败后，必须先有该页的失败 checkpoint，才能预演重试：

```powershell
py -3.12 -B scripts/parsing_architecture.py retry-page <source_id> <页码>
py -3.12 -B scripts/parsing_architecture.py retry-page <source_id> <页码> --save
```

默认命令不写文件；`--save` 只保存一条单页重试元数据，仍不会调用解析器。每页最多重试 2 次，原基础结果始终保留。

## 什么时候运行增强解析

PaddleOCR-VL 已作为本地主增强器，但仍只应处理质量路由选出的异常页。先运行 dry-run，单批最多 25 页、并发 1；自动检查失败的页面进入 `exception_review`，固定少量样本进入 `sample_review`。MinerU 只用于少量对照诊断，不应与主解析器并发批量运行。首次扩大范围前要比较符号正确性、题序、耗时、内存、显存和磁盘增量，不得直接对全库启用。

不要一次性重跑全库。大批量重跑会放大错误、占满磁盘并掩盖单页失败。每次选择明确的课程、科目、资料类型或 source_id，先看资源估算，再按不超过 25 页的批次处理，完成验证和 checkpoint 后才进入下一批。

[[学习主页|返回首页]] · [[00-系统维护/Scalable-Parsing-Architecture|可扩展解析架构]] · [[00-系统维护/Validation-Guide|验证说明]]
