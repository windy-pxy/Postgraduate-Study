# study_readonly_pilot

本文件是 Claudian + Codex 在本 vault 中的强制项目规则。当前试点只允许学习资料检索、阅读、解释和带来源引用的问答。

## 运行边界

- Claudian 的 Codex Provider 必须设置为 `read-only`，权限模式不得设为 YOLO。
- 不执行 shell、命令、脚本、下载、依赖安装、网络工具、外部 API、MCP 或子代理；不要建议绕过这些限制。
- 只读取 vault 内已有文件。不得修改、移动、重命名或删除任何现有文件。
- 永远不得修改、移动、删除或覆盖 `90-Parsed-Sources/`、项目根目录的 `sources-original/`、`import-inbox/`、`config/source-manifests/`、`config/sources-original.baseline.json`、`review-queue/`。
- 不得自行把候选内容标为 accepted/approved，不得改变审核状态。
- 任何删除都必须先取得用户明确确认；本试点的只读模式仍不得执行删除。

## 检索与回答

- 正式问答只可使用 `90-Parsed-Sources/<source_id>/accepted/` 下已明确人工审核为 `accepted` 的内容。
- 当前没有匹配的已审核内容时，原样回答“暂无已审核资料”，然后说明可以由用户明确要求查看待审核候选预览；不得用候选内容补成正式答案。
- 只有用户明确要求“预览待审核候选”时，才可读取基础或增强候选。输出必须逐项显示：`review_required`、`source_id`、原始页码、`parser_id` 与 `parser_version`。
- 基础候选和增强候选必须分开列出；同页多版本不得合并，不得把候选表述为教材事实或已确认结论。
- 每个事实性回答或候选片段都必须附 Obsidian 双链；无法生成双链时，给出明确的 vault 相对路径。来源和页码不确定时直接说明，不得编造。
- 只能解释实际读到的内容，不得编造学科结论、公式、引用或页码。

## 草稿

- 仅当用户明确包含“生成草稿”四个字时，才可以提出在 `03-Knowledge-Notes/AI-Drafts/` 新建草稿。
- 当前 `read-only` 试点不能实际写入草稿。需要写入时，必须结束当前会话，由用户另行授权受控写入；不得为了写草稿放宽本会话权限。
- 即使未来获准生成草稿，也只能新建，不覆盖同名文件，并必须保留来源、页码和 `draft` 状态。
