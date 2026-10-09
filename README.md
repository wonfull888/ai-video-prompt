# video-prompt-reverse (BestPrompts pipeline skill)

Fork 自 LunarXuan/video-prompt-reverse，分析流水线复刻 bestprompts.app video-to-prompt（PRO 单次调用版），模型 `google/gemini-3.8-flash`（OpenRouter）。

## Quickstart

```bash
export OPENROUTER_API_KEY=sk-or-...
python3 scripts/reverse.py /path/to/video.mp4 --out outputs/demo
```

Cursor / Codex：`视频反推提示词 <视频路径>`。
