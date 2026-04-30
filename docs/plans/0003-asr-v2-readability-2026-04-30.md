# Plan 0003 - ASR 可读性 V2（节奏/弱词/行宽）

## Date
- 2026-04-30

## Summary
- 在现有 ASR 前置修复基础上，把优化目标从“结构正确”推进到“阅读体验更稳定”。
- 本轮只改规则层，不引入 LLM 重写。

## Root Cause（代码出处）
- `normalize_subtitle_timeline()` 仅覆盖轻兜底，缺少节奏归一与弱词起句修复。  
  文件：`src/subtitle_maker/transcriber.py`
- `format_srt()` 直接单行输出，未做 42 字符级显示换行。  
  文件：`src/subtitle_maker/transcriber.py`

## Key Changes
1. 时间节奏归一（前置）
- `<2s` 强并句，`<2.5s` 的弱词/标点起句优先并句。
- `>6s` 长句拆分，并允许按文本长度触发拆分，时间按文本比例映射。

2. 弱词与标点修复（前置）
- 新增句首弱词检测（`and/but/so/because/that/is...`）。
- 清理句首孤立标点（`, . : ;`）并尽量回并上一句。
- 拆分后再执行一次句首修复，减少新切点副作用。

3. SRT 显示换行（输出层）
- 新增 `_wrap_subtitle_lines()`，按 42 字符宽度优先 1~2 行排版。
- 明确禁止截断文本内容（仅换行，不删字）。

4. 回归测试
- 扩展 `tests/test_transcriber_asr_layout.py`：
  - 弱词起句并回；
  - 超长句拆分；
  - 句首标点修复；
  - 42 字符换行。

## Validation
- `uv run python -m py_compile src/subtitle_maker/transcriber.py tests/test_transcriber_asr_layout.py`
- `uv run python -m unittest tests.test_transcriber_asr_layout`
- `uv run python -m unittest tests.test_web_routes_legacy`

## Sample Output
- 样本输入：`/Users/tim/Downloads/64e5f172-1cd4-4e1d-a3b2-bed953c6e990.srt`
- 规则输出：`/Users/tim/Downloads/64e5f172-1cd4-4e1d-a3b2-bed953c6e990.v2.srt`
