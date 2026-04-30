# Plan 0002 - Panel 3 高度对齐（Original 对齐 Translation 编辑区）

## Date
- 2026-04-30

## Summary
- 目标：`✏️ Editor & Translation` 中左侧 `Original` 显示框高度与右侧 Translation 编辑区一致。
- 范围：不包含 Export 区高度。
- 方式：纯前端结构重排 + CSS 等高，不使用 JS 动态测高。

## Key Changes
1. 模板结构调整（`index.html`）
- 在 `#panel-results` 中把右侧“翻译参数 + 提示词 + Translate + translated-subtitles”封装为 `translation-workspace`。
- `subtitle-editor` 仅保留左右两列编辑区：`Original` 与 `Translation`。
- 将 `Export Final`、`Export Audio Segments` 移到 `subtitle-editor` 下方，放入 `subtitle-export-stack`。
- 保持核心控件 ID 不变（`translated-subtitles`、`export-btn`、`export-segments-btn` 等），确保既有 JS 绑定可复用。

2. 样式调整（`style.css`）
- `subtitle-editor` 增加 `align-items: stretch`，保证两列可等高。
- 左侧 `Original` 列改为拉伸：`#original-subtitles` 使用 `flex: 1; height: auto; min-height: 380px;`。
- 新增 `translation-workspace` 与 `subtitle-export-stack` 样式，维护拆分后的间距和层次。
- 保持移动端单列规则（<=768px），防止布局溢出或遮挡。

## Test Plan
1. Panel 3 中左侧 `Original` 显示框与右侧 Translation 编辑区（不含 Export）视觉等高。
2. `Translate`、`Download`、`Export ZIP` 按钮行为不回归。
3. 原文/译文字幕继续可渲染、可滚动。
4. 移动端单列下顺序正确，无重叠、无裁切。

## Assumptions
- 高度对齐范围固定为“右侧翻译编辑区”，不包含 Export。
- 不改后端 API、不改数据结构、不改参数契约。
