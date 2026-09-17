# 本地公式增强解析指南

本项目采用 MinerU 4.0.0 Standard 档作为首个真实可运行的页面增强器。它使用项目内隔离环境、ONNX 小模型和 llama.cpp 本地视觉语言模型，只处理质量路由明确标记为 `enhanced_parse_queued` 的单页。基础 PyMuPDF 结果、增强候选和人工接受结果始终分开。

## 本地环境与模型

- 环境：`.venv/mineru/`
- 模型与下载缓存：`models/cache/`
- 固定依赖：`config/mineru-4.0.requirements.lock.txt`
- 解析配置、模型 revision 和关键文件 SHA-256：`config/enhanced-parser.example.json`

这两个目录都不进入 Git。关键文件哈希用于发现本地文件变化，是本机计算值，不是模型发布者的数字签名或真实性证明。GGUF 模型卡声明 Apache-2.0；ONNX 聚合仓库的模型卡元数据没有声明统一许可证，重新分发前必须逐个复核上游组件许可证。MinerU 程序本身使用其仓库中的 MinerU Open Source License。

下载只在安装阶段进行。正常推理设置 Hugging Face/Transformers 离线变量、`MINERU_MODEL_SOURCE=local`，并在 worker 内阻止 socket 连接。输入 PDF 不发送到外部服务。模型原生运行库可能向 stderr 输出初始化警告；控制器只记录字节数，不保存或回显这些内容。

## 单页命令

以下命令只接受已登记 source_id 和从 1 开始的页码：

```powershell
py -3.12 -B scripts/enhanced_parser.py model-status
py -3.12 -B scripts/enhanced_parser.py inspect <source_id> <页码>
py -3.12 -B scripts/enhanced_parser.py parse <source_id> <页码>
py -3.12 -B scripts/enhanced_parser.py parse <source_id> <页码> --apply
py -3.12 -B scripts/enhanced_parser.py verify-output <source_id> <页码>
py -3.12 -B scripts/enhanced_parser.py report <source_id> <页码>
```

`parse` 默认 dry-run。`--apply` 前会重算来源完整性、检查路由、验证模型哈希和确认目标不存在。每次只处理一页，并发为 1。目标固定为：

```text
vault/90-Parsed-Sources/<source_id>/enhanced/mineru/page-XXXX/
├─ page-preview.png
├─ mineru.md
├─ mineru-result.json
├─ worker-report.json
├─ candidate-manifest.json
└─ review.md
```

新目录先在同一父目录下构建，来源再次校验且文件齐全后才原子发布。基础输出和原件不会改变；目标存在即拒绝重复解析。失败目录保留固定错误报告供恢复检查，不冒充成功。高置信疑似密钥会阻止发布，错误报告只记录风险类型，不包含原文。

## 如何判断是否改善

替换字符减少和 LaTeX 可渲染都不能证明数学正确。人工审核至少逐项核对：

- 上下标属于哪个字符；
- `[x]补`、`[x]原` 的括号、变量和中文记号；
- 正负号、不等号、积分上下限和矩阵行列；
- 题干、选项、表格及多栏阅读顺序；
- 中文、英文标识符、数字和标点是否遗漏或串接。

合成评估源位于 `tests/fixtures/parsing-evaluation/`。开发集用于暴露问题；`held_out` 明确不用于调参。生成的 PDF、预览、模型输出和真实页面对照只保存在被忽略的测试/审核目录。评估摘要不能替代真实页面逐字符人工标注，也不能据此宣称真实资料准确率。

## 当前已知限制

MinerU 能恢复部分上下标、分式、根号、积分和表格结构，但仍可能丢失负号、误组公式、压平矩阵或分段函数、拆分数字，并改变题目阅读顺序。当前来源第 2 页的替换字符明显减少，但核心补码表达仍有错误，且存在题干遗漏，因此保持 `review_required`，不得进入 `accepted/` 或正式知识笔记。

模型冷启动和页面推理需要数秒到数十秒。资源指标属于运行时观测值，系统可用内存变化包含同期其他进程；单个 worker 进程内存不代表全部子进程。异常页逐页处理仍是默认策略。

入口：[[00-System/PDF-Parsing-Guide|PDF 解析指南]] · [[00-System/Scalable-Parsing-Architecture|可扩展解析架构]] · [[00-System/Validation-Guide|验证说明]]
