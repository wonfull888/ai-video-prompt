# ai-video-prompt

[中文版](README.zh-CN.md) | English (default)

Turn any reference video into ready-to-use bilingual (Chinese + English) generation prompts. Upload a video, get back shot breakdowns, evidence frames, and copy-paste prompt packages.

## Who Is It For

- Creators using Cursor / Codex for AI series, shorts, or ads who want to turn a reference video they found into their own generation prompt.
- Typical case: you see a 15-second anime tavern scene and want to recreate its camera work and acting with Veo / Sora / Kling — reverse it into a prompt, then adapt.

## Features

- Full video-analysis pipeline: scene-detect evidence → Gemini reads the whole video for a first structured pass → dense multi-window motion re-reviews of risky segments → independent expression review → reconcile & cleanup → bilingual render.
- Bilingual Markdown by default: `prompt.md` ships Chinese first, English second, plus split `prompt_zh.md` / `prompt_en.md`.
- No identity swaps: characters are labeled with readable names in every beat (e.g. `Character P01 (barmaid)`), and identities are locked during reconcile.
- Uncertainty when unsure: blurry transitions and tiny props are reported as uncertain instead of invented — no made-up causes or dialogue.
- One-line Cursor / Codex trigger: say "video-to-prompt + video path" and it runs.

## Demo

Real test output below (15.6s anime clip, `google/gemini-3.8-flash`): opening → bottle grab → ending solo.

![opening](docs/demo/frame-opening.png)
![bottle grab](docs/demo/frame-grab.png)
![ending](docs/demo/frame-ending.png)

Excerpt from the generated `prompt.md` (English block):

```text
### Shot S02 · 6.80–13.17s
Angle / composition / movement：medium shot；eye-level；two-shot；slight push-in
Action beat 1 · 6.80–8.05s
  Character P01 (patron): Action: Reaches his right hand toward the liquor bottle,
  grips it, and lifts it off the counter to chest height.
  Character P02 (barmaid): Action: Stands behind the counter, hand on the black book.
```

## Installation

Requirements: Python 3.10+, `ffmpeg` (with `ffprobe`), one OpenRouter key (vision model) and one DeepSeek key (reconcile/translate).

```bash
git clone https://github.com/wonfull888/ai-video-prompt.git
cd ai-video-prompt
export OPENROUTER_API_KEY=sk-or-...
export DEEPSEEK_API_KEY=sk-...
```

Keys live in environment variables only — never in the repo (only `.env.example` documents the key names).

## Usage

```bash
python3 scripts/reverse_full.py /path/to/video.mp4 --out outputs/demo
```

Input: one video under 30 seconds (mp4 / mov / webm). The output folder's `prompt.md` is the deliverable, plus `structured.json` (structured data), `evidence_gallery.md` (evidence frames), `shots.md` (shot table), and `manifest.json` (model/call record).

## Notes & License

- Videos must be under 30 seconds; oversized videos are downscaled to 960p before analysis.
- Blurry transitions and tiny-object details in low-bitrate videos may be marked "uncertain" — this is a reverse-engineered spec, not the original prompt, so don't expect word-for-word fidelity.
- Cost: roughly 6–10 model calls per run (vision via OpenRouter, text via DeepSeek) — watch your key quotas.
- License: MIT, see [LICENSE](LICENSE).
