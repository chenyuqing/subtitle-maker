# Agent 入口 V1

日期：2026-04-24

## 定位

Agent V1 是产品内使用帮助助手，不是自动执行代理。

它解决的问题：

- 用户不知道下一步点哪里。
- 用户遇到失败但不想读日志。
- 用户不理解参数含义。
- 用户需要知道如何修复字幕/翻译/配音链路问题。

## 能力边界

| 项目 | 决策 |
|---|---|
| 入口 | 右下角浮动抽屉。 |
| 模型 | DeepSeek `deepseek-v4-flash`。 |
| Base URL | `https://api.deepseek.com`。 |
| API Key | 用户输入优先，其次 `DEEPSEEK_API_KEY`。 |
| 能力 | 使用帮助、报错解释、下一步建议。 |
| 禁止 | 不修改文件、不执行任务、不重配、不删除产物。 |
| 上下文 | V1 只接收用户问题和当前页面名。 |
| 数据收集 | 可本地记录匿名问题类型，后续优化产品。 |

## 第一版实现策略

Agent V1 先作为独立产品增量实现，不等待完整 `app/routes/*` 架构落地。

| 项目 | 决策 |
|---|---|
| 后端位置 | 先新增 `src/subtitle_maker/agent_api.py`，使用 `APIRouter(prefix="/api/agent")`。 |
| 复用策略 | 新增 `src/subtitle_maker/core/llm_client.py`，避免把 Agent 逻辑塞进 `Translator`。 |
| Web 接入 | 迁移期由 `src/subtitle_maker/web.py` include router。 |
| 前端接入 | 暂时接入现有 `templates/index.html`、`static/app.js`、`style.css`，但命名以 `agent-*` 前缀隔离。 |
| 后续迁移 | 等 Web API 拆分时，再把 `agent_api.py` 移到 `app/routes/agent.py`。 |

## API

```http
POST /api/agent/chat
```

请求：

```json
{
  "message": "为什么配音失败了？",
  "conversation_id": "optional",
  "page": "auto-dubbing-v2",
  "api_key": "optional"
}
```

请求字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `message` | 是 | 用户问题，去除首尾空白后不能为空。 |
| `conversation_id` | 否 | 前端会话 ID，缺失时后端生成。 |
| `page` | 否 | 当前页面或 panel，例如 `auto-dubbing-v2`。 |
| `api_key` | 否 | DeepSeek key；为空时读取 `DEEPSEEK_API_KEY`。 |

响应：

```json
{
  "conversation_id": "session-id",
  "reply": "失败原因解释和下一步建议",
  "suggested_actions": [
    "检查 DeepSeek API Key",
    "确认 Index-TTS 服务是否启动"
  ]
}
```

响应字段：

| 字段 | 说明 |
|---|---|
| `conversation_id` | 本次会话 ID，用于前端继续对话。 |
| `reply` | Agent 回复正文。 |
| `suggested_actions` | 1 到 5 条短操作建议；如果模型未返回结构化动作，后端可返回空数组。 |

错误响应方向：

| 场景 | HTTP | code | message |
|---|---|---|---|
| API key 缺失 | 400 | `E-AGENT-001` | 需要 DeepSeek API Key 或配置环境变量。 |
| DeepSeek 401 | 401 | `E-AGENT-002` | API Key 无效或无权限。 |
| 请求超时 | 504 | `E-AGENT-003` | DeepSeek 请求超时。 |
| provider 错误 | 502 | `E-AGENT-004` | DeepSeek 返回错误。 |
| 空消息 | 400 | `E-AGENT-005` | 请输入问题。 |

## System Prompt 要求

Agent 必须遵守：

- 只能给建议，不能声称已经执行操作。
- 不要求用户上传 API key 到不明位置。
- 不编造文件或日志内容。
- 如果没有上下文，明确说明需要用户贴出错误信息。
- 对常见问题给出短步骤，不输出大段架构解释。
- 优先使用项目实际术语：ASR、source.srt、translated.srt、Auto Dubbing V2、Index-TTS、DeepSeek、review、redub。

Prompt 必须固定写入以下边界：

```text
你是 Subtitle Maker 的产品内使用助手。
你只能解释功能、排查错误、建议下一步。
你不能执行任务、不能修改文件、不能删除产物、不能声称已经完成任何操作。
如果用户要求你执行操作，你必须说明你只能提供手动操作建议。
如果用户没有提供足够错误信息，你必须要求用户粘贴错误文本或说明当前页面。
```

内置知识：

| 问题 | 建议方向 |
|---|---|
| DeepSeek API Key required | 检查翻译/Agent key 或 `DEEPSEEK_API_KEY`。 |
| Index-TTS 服务不可用 | 启动本地 Index-TTS 服务，检查 `127.0.0.1:8010/health`。 |
| ASR 字幕很零散 | 检查智能分句和短句合并设置。 |
| 上传 translated 字幕 | 会跳过翻译，直接配音。 |
| source 字幕 | 会作为原文侧，仍需要翻译。 |
| redub 失败 | 不应破坏旧音频，建议查看 review 错误和 batch manifest。 |

## 前端交互

| 元素 | 行为 |
|---|---|
| 浮动按钮 | 固定右下角，避开播放器控件。 |
| 抽屉 | 从右侧滑出，不改变主布局。 |
| API Key 输入 | password 类型，不自动持久化。 |
| 消息输入 | Enter 发送，Shift+Enter 换行。 |
| 历史消息 | 当前浏览器会话内保存。 |
| Loading | 请求中显示“正在分析”。 |
| 错误态 | 明确显示 key 错误、超时、网络错误。 |

## 安全边界

| 风险 | 控制 |
|---|---|
| API key 泄露 | 不落盘、不打印、不返回。 |
| Agent 幻觉执行能力 | prompt 和 UI 都说明“只提供建议”。 |
| 错误建议过泛 | 内置项目流程和常见错误知识。 |
| 用户要求危险操作 | 明确拒绝执行，只说明手动操作风险。 |
| 日志敏感信息 | V1 不自动读取日志。 |

## Provider 调用策略

| 项目 | 决策 |
|---|---|
| SDK | 复用 `openai` Python package 的 OpenAI-compatible client。 |
| 默认 base URL | `https://api.deepseek.com`。 |
| 默认 model | `deepseek-v4-flash`。 |
| timeout | 第一版使用 30 秒。 |
| temperature | `0.2`，降低排查建议发散。 |
| API key | 仅内存使用，不写入日志、不写入响应、不写入 localStorage。 |
| 错误处理 | 后端捕获 provider 异常并转成 `E-AGENT-*`。 |

## 前端状态

| 状态 | 存储位置 |
|---|---|
| 抽屉打开/关闭 | 当前页面内存即可。 |
| 消息历史 | `sessionStorage`，刷新浏览器标签页后可恢复，关闭标签页后丢弃。 |
| API key | 只保存在 input DOM，不写 `localStorage` / `sessionStorage`。 |
| conversation_id | `sessionStorage`。 |

## 实现位置

第一版建议：

| 文件 | 改动 |
|---|---|
| `src/subtitle_maker/core/llm_client.py` | 新增 OpenAI-compatible chat client。 |
| `src/subtitle_maker/agent_api.py` | 新增迁移期 Agent route。 |
| `src/subtitle_maker/web.py` | 迁移期 include agent router。 |
| `src/subtitle_maker/templates/index.html` | 添加浮动按钮和抽屉结构。 |
| `src/subtitle_maker/static/app.js` | 添加抽屉交互和请求逻辑。 |
| `src/subtitle_maker/static/style.css` | 添加 Agent 样式。 |
| `tests/test_agent_api.py` | 新增 API 测试。 |

## 测试计划

| 测试 | 标准 |
|---|---|
| key 缺失 | 返回 `E-AGENT-001`。 |
| 空消息 | 返回 `E-AGENT-005`。 |
| 401 | 返回可读 API Key 错误。 |
| 超时 | 返回可读超时错误。 |
| 普通问题 | 返回 `reply` 和 `suggested_actions`。 |
| 禁止执行 | 用户要求删除/重配/修改文件时，只给建议，不执行。 |
| 日志脱敏 | 响应和日志不包含 API key。 |

## Review 3 结论

Agent V1 是第一批实现任务，但必须保持独立和低风险。它只新增帮助入口，不接入任务执行、不读取本地 manifest、不改变现有上传/翻译/配音链路。后续如果要让 Agent 读取任务状态，必须单独进入 V2 文档和 review。
