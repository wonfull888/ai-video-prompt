---
name: video-prompt-reverse
description: "BestPrompts.app video-to-prompt pipeline as a reusable skill: reverse-engineer any local video into bilingual (Chinese + English) generation prompts via google/gemini-3.8-flash on OpenRouter. Use for 视频反推提示词, 视频转提示词, 从视频生成提示词, video-to-prompt."
---

# Video Prompt Reverse (BestPrompts pipeline)

将本地视频反推为可直接复制的中英双语生成提示词。逻辑复刻 `bestprompts.app` 的 video-to-prompt PRO 流水线：视频取证 → Gemini 结构化分析 → 中英渲染。

## 前置要求

- `ffmpeg` / `ffprobe` 可用。
- 环境变量（绝不写入仓库，用 `.env.example` 只给键名）：
  - `OPENROUTER_API_KEY`（必填）
  - `OPENROUTER_BASE_URL`（默认 `https://openrouter.ai/api/v1`）
  - `OPENROUTER_GEMINI_MODEL`（默认 `google/gemini-3.8-flash`）
  - `OPENROUTER_GEMINI_PROVIDER`（默认 `google-ai-studio/flex`）

本地开发可 `set -a; source /path/to/bestprompts/.env; set +a` 临时载入已有 key，禁止把 `.env` 复制进本仓库。

## 使用（Cursor / Codex 快捷方式）

- Cursor / Codex 中直接说：`视频反推提示词 <视频路径>`、`video-to-prompt <视频路径>`。
- Agent 看到上述触发词即执行本 Skill 的脚本，无需追问：

```bash
python3 scripts/reverse.py <视频路径> --out outputs/<任务名>
```

输出目录包含：`structured.json`、`prompt_zh.txt`、`prompt_en.txt`、`evidence_gallery.md`、`manifest.json`、抽帧 `frames/`。

## 流水线（与 bestprompts 对齐）

1. `ffprobe` 取 duration / 分辨率 / fps / sha256（见 `scripts/probe_video.py`）。
2. 按时长抽 6-10 帧关键证据帧（ffmpeg，原始帧不做美化）。
3. 调 OpenRouter `google/gemini-3.8-flash`：PRO 结构化分析 prompt（源自 `bestprompts/bp/pro.py` 的 `PRO_ANALYSIS`，精简为单次调用 + 证据帧），返回 story / global / shots / negative_constraints / uncertainties 的 JSON。
4. 第二次调用同一模型做英译中（保持原意与不确定性，不补事实）。
5. 按 `render_pro` 规则渲染 `prompt_zh.txt` / `prompt_en.txt`：先中文块（正面+负面），再英文块（正面+负面），负面约束按身份/肢体/服装道具/环境/运动物理/镜头剪辑/渲染分组。
6. `scripts/validate_spec.py` 校验结构后交付。

## 输出规范

- 必须返回：分镜表（编号/起止/景别角度/运镜/动作表情/转场/置信度）+ 内联证据图（绝对路径）+ 两个可复制代码块（中文块在前、英文块在后）。
- 不声称是原视频的“原始 prompt”，统一称为反推生成规格。
- 不编造焦距、灯具、品牌、台词、因果；不确定的写进 uncertainties。

## 参考

- `references/analysis-contract.md`：结构化字段契约。
- `references/model-adapters.md`：veo / sora / kling / wan 适配（按需读取）。
- 完整多阶段 PRO（motion_review / expression_review / reconcile / causal_cleanup）见上游 bestprompts `bp/pro.py`；本 skill 默认单次分析保证速度，需要逐帧取证时再按上游加阶段。
