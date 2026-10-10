---
name: ai-video-prompt
description: "BestPrompts.app video-to-prompt pipeline as a reusable skill: a vision model watches the whole video and reverse-engineers it into bilingual (Chinese + English) generation prompts, then a text model fact-checks and translates. Use for 视频反推提示词, 视频转提示词, 从视频生成提示词, video-to-prompt."
---

# AI Video Prompt (BestPrompts pipeline)

用户在 Cursor / Codex 里说一句"视频反推提示词 + 视频路径"，你就接管：看完视频，交出一份最大程度还原的中英双语 prompt，简单改改就能拿去生成。

## 模型分工（先搞清谁在干活）

- 视觉模型（看的活）：`google/gemini-3.8-flash`（经 OpenRouter）。它直读完整视频，做场景切分、初版结构化分析、可疑动作段的稠密复查、表情审查。这是核心，还原质量全靠它。
- 文字模型（审核翻译的活）：DeepSeek（经 `DEEPSEEK_BASE_URL`）。它做对账清洗（删掉证据站不住的因果）、故事重写、英译中。不用 agent 自带模型的原因：流水线要按固定流程调好几次 API、用自己的 Key，塞不进聊天上下文；分开也更便宜稳定。文字模型可通过环境变量换（`VIDEO_BLUEPRINT_DEEPSEEK_MODEL`）。
- Agent（你）只管一句话唤起，不参与看视频。

## 前置要求

- `ffmpeg` / `ffprobe` 可用。
- 环境变量（绝不写入仓库，用 `.env.example` 只给键名）：
  - `OPENROUTER_API_KEY`（必填，视觉）
  - `DEEPSEEK_API_KEY`（必填，审核翻译）
  - `OPENROUTER_GEMINI_MODEL`（默认 `google/gemini-3.8-flash`）
  - `OPENROUTER_GEMINI_PROVIDER`（默认 `google-ai-studio/flex`）

## 使用（用户只说一句话）

- 用户说：`视频反推提示词 <视频路径>` 或 `video-to-prompt <视频路径>`。
- 你看到触发词即运行，无需追问（底下实际就一条命令）：

```bash
python3 scripts/reverse_full.py <视频路径> --out outputs/<任务名>
```

默认交付物是 `prompt.md`（中英双版合一 md，中文块在前、英文块在后）；另有 `prompt_zh.md` / `prompt_en.md`、`structured.json`、`evidence_gallery.md`、`shots.md`、`manifest.json`。`scripts/reverse.py` 仅为快速单次版，默认不用。

## 流水线（与 bestprompts 对齐）

1. 取证：`ffprobe` 拿时长/分辨率/fps/sha256；场景检测切镜头（阈值自适应），抽证据帧（原始帧不美化）。
2. 初版分析：完整视频直传 Gemini（`PRO_ANALYSIS`），`validate_pro` 校验镜头/动作阶段全覆盖。
3. 多窗口复查：按因果词密度取 Top-N 可疑窗口（通用规则，不针对单个视频），每段稠密帧做 `motion_review`；原分辨率稀疏帧做 `expression_review`。
4. 对账清洗：`reconcile` 合并多份审查（人物身份锁定、动作阶段只增不减、离场只许写离开画面、特效标不确定），`causal_cleanup` 去无依据因果，`story` 重写。
5. 双语渲染：`translate` + 缺失补齐 → `render_pro` 输出中英；人物标签带身份名（如`人物 P01（女招待）`）。

## 输出规范

- 必须返回：分镜表 + 内联证据图（绝对路径）+ 两个可复制代码块（中文块在前、英文块在后）。
- 不声称是原视频的"原始 prompt"，统一称为反推生成规格（最大程度还原，简单修改即可使用）。
- 不编造焦距、灯具、品牌、台词、因果；不确定的写进 uncertainties。
- 提醒用户：生成视频要花真钱，使用前自己过一遍 prompt 再改。

## 参考

- `references/analysis-contract.md`：结构化字段契约。
- `references/model-adapters.md`：seedance / veo / sora / kling / wan / generic 适配（按用户要生成的目标模型读取，默认 generic；Seedance 2.5 中英文原生都可）。
