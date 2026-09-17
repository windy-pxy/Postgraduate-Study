# Claudian 只读学习问答试点

本试点把 Obsidian 中的 Claudian 连接到本机已有 Codex CLI，用于日常讲解、读取用户明确指定的资料，以及严格的已审核资料查询。它不改变来源审核状态，也不把待审核候选当作正式知识。项目规则位于 vault 根目录的 [[AGENTS|study_readonly_pilot]]，日常入口见 [[日常辅导]]。

## 已核对的环境

- Obsidian 当前窗口版本为 1.13.7，满足 Claudian 2.2.7 要求的 Obsidian 1.13.0 以上桌面版。
- Codex CLI 为 `codex-cli 0.154.0-alpha.6.2`，`codex app-server --help` 可用。
- Codex 已通过 ChatGPT 登录。不要在笔记、设置说明或截图中记录令牌。
- Claudian 官方插件 ID 为 `realclaudian`，官方仓库为 `YishenTu/claudian`。只使用 Obsidian 设置中的“社区插件”页面安装，不从源码构建，不运行第三方安装脚本。

Claudian 会把用户输入、明确附加的文件和工具输出发送给所选提供器。选择 Codex 时，回答请求会经 Codex 提供器传输；“工具网络关闭”不等于提供器完全离线。不要附加原始资料或未审核全文，只让试点定位必要的页级内容。

## 官方 UI 安装与设置

1. 在已打开的 `D:\Postgraduate-Study\vault` 中进入“设置 → 第三方插件/社区插件 → 浏览”。
2. 搜索 **Claudian**，确认插件 ID 为 `realclaudian`，安装并启用。
3. 在 Claudian 设置中启用 **Codex** Provider，Windows 安装方式选择 **Native Windows**。
4. CLI 路径先留空让插件自动发现；只有自动发现失败时，才在 UI 中选择现有 `codex.exe`。不要修改全局 PATH。
5. 将 **Codex safe mode** 明确设为 **read-only**，并确认聊天栏权限切换显示 **Safe**。不要选择 workspace-write 或 YOLO。
6. 保持 MCP、子代理、Collab 和其他 Provider 关闭。本试点不填写 API Key，也不设置自定义环境变量。

Claudian 的每 vault 设置、会话和运行记录保存在 `.claudian/`，Obsidian 插件文件与设备配置保存在 `.obsidian/`；两者都只留本机并被 Git 忽略。不要把会话记录当作正式笔记或审核证据。

Claudian 2.2.7 的默认 Codex safe mode 是 workspace-write，因此每次重装、升级或重置设置后都要重新检查。项目内规则是语义保护，真正的文件系统保护来自 `read-only` 沙箱；两者必须同时存在。

## 首次试点

新建一个 Claudian 会话后，先确认会话工作目录是当前 vault，再逐条输入：

1. `请按 study_readonly_pilot 正式回答：补码。`
   预期只返回“暂无已审核资料”，并可提示用户显式预览；不得引用候选作答。
2. `预览待审核候选：只查 source_id src-e1df768ce191 第 2 页中的补码，分别列出 basic 与 enhanced，不要总结为教材事实。`
   预期每项显示 `review_required`、source_id、页码、parser_id、parser_version，并提供 Obsidian 双链或 vault 相对路径。
3. 点击结果中的 Obsidian 双链，确认能定位到对应基础页或增强候选。基础与增强必须是两个独立结果。

候选预览需要 Codex 在 `read-only` 沙箱中列目录、搜索并读取 vault 内的 Markdown；允许的只读操作包括 `Get-ChildItem`、`rg`、`Get-Content` 等。不得运行项目脚本、使用输出重定向或执行任何写入、下载、安装、联网命令。若 Claudian 请求写入、提升权限或启用网络工具，立即拒绝并结束会话。若严格资料查询引用了候选、遗漏审核状态或合并同页版本，则试点不通过，不继续使用该会话。

## 日常使用

- 一般知识问题可以直接提问；回答应标为“模型补充”，没有资料依据时不生成虚假引用。
- 指定候选页面时，要求回答标注“待审核候选”、source_id 和原始 PDF 页码，并把识别不确定处单独列出。
- 只有明确说“严格资料查询”时才进入 accepted 门禁；当前无 accepted 内容时仍回答“暂无已审核资料”。
- 需要保存时，让助教输出可复制 Markdown，再手动粘贴到知识笔记或错题本。只读会话不创建文件。

## 项目侧只读验证

下面的命令不调用 Claudian 或模型，只验证规则和本地检索契约：

```powershell
py -3.12 -B scripts/validate_claudian_pilot.py check-policy
py -3.12 -B scripts/validate_claudian_pilot.py run-pilot
```

`run-pilot` 不输出正文，只检查正式查询为空、显式预览能定位第 2 页、basic/enhanced 分离、风险状态和链接字段完整。它不能替代 UI 内的人工试问。

## 草稿和审核

当前只读会话不能写文件。只有用户明确说“生成草稿”并另行授权受控写入后，才可在 `03-知识笔记/AI-草稿/` 新建草稿。候选内容仍需人工对照原页；Claudian 无权把内容标为 accepted，也无权把草稿移入正式笔记区。

[[学习主页|返回首页]] · [[00-系统维护/Local-Retrieval-Guide|本地检索指南]] · [[00-系统维护/Validation-Guide|验证说明]]
