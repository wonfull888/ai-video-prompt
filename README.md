# ai-video-prompt

[中文版](README.zh-CN.md) | English (default)

Give it a reference video, get back a prompt that restores it as faithfully as possible — light editing and it's ready to generate with. You receive shot breakdowns, evidence frames, and a bilingual prompt file.

## Who Is It For

- You make AI videos (shorts, series, ads) in Cursor or Codex, and you found a reference clip you want to recreate — same camera moves, same acting, same vibe.
- Say the word in your code agent ("video-to-prompt + video path") and the skill does the watching and writing for you.

## Features

- A vision model watches the whole video (not just screenshots): it splits shots, tracks who does what, how the camera moves, and facial expressions — this is the core work, done by `google/gemini-3.8-flash` through OpenRouter.
- A text model then double-checks the draft: it re-examines the tricky action segments frame by frame, deletes anything the frames can't prove, and translates everything into Chinese (done by DeepSeek; swappable via env vars).
- Bilingual Markdown by default: `prompt.md` ships Chinese first, English second, plus split `prompt_zh.md` / `prompt_en.md`.
- Characters keep readable names in every beat (e.g. `Character P01 (barmaid)`), and identities are locked so the model can't swap people mid-review.
- Works for the models you actually generate with: Seedance 2.5 / 2.0, Veo, Sora, Kling, Wan, plus generic — see `references/model-adapters.md`.

Why not just use your code agent's own model? Two reasons: the pipeline sends raw video bytes plus dozens of frames through a reproducible multi-call flow with its own API keys — that doesn't fit an agent chat context; and splitting "seeing" (Gemini) from "fact-checking and translating" (DeepSeek) keeps each step cheap and stable. Your agent stays the boss that invokes the skill.

## Demo

Real test output below (27s fantasy-battle montage, `google/gemini-3.8-flash`): opening → key action → ending.

![opening](docs/demo/frame-opening.png)
![key action](docs/demo/frame-grab.png)
![ending](docs/demo/frame-ending.png)

Excerpt from the generated `prompt.md` (English block):

```text
### Shot S01 · 0.00–1.20s
Angle / composition / movement: medium shot; low angle; tracking right
Action beat 1 · 0.00–1.20s
  Character P01 (protagonist): Action: Slides on grass while swinging
  a flaming greatsword through shadow demons; Motion: sliding rightward
```

## Installation

Requirements: Python 3.10+, `ffmpeg` (with `ffprobe`), one OpenRouter key (vision model) and one DeepSeek key (review/translate).

```bash
git clone https://github.com/wonfull888/ai-video-prompt.git
cd ai-video-prompt
export OPENROUTER_API_KEY=sk-or-...
export DEEPSEEK_API_KEY=sk-...
```

Keys live in environment variables only — never in the repo (only `.env.example` documents the key names).

## Usage

In your code agent (Cursor / Codex), just say:

```text
video-to-prompt /path/to/video.mp4
```

The agent invokes this skill and runs the pipeline for you. Under the hood it's one command (input: one video under 30 seconds, mp4 / mov / webm):

```bash
python3 scripts/reverse_full.py /path/to/video.mp4 --out outputs/demo
```

The output folder's `prompt.md` is the deliverable, plus `structured.json` (structured data), `evidence_gallery.md` (evidence frames), `shots.md` (shot table), and `manifest.json` (model/call record).

## Notes & License

- 30 seconds max by default; you can raise it yourself in `probe_video` inside `scripts/reverse_full.py` (longer videos cost more calls).
- Before spending real money generating: read through the prompt once and fix names/details to your taste — the output restores the reference, it doesn't know your project's characters.
- Cost: roughly 6–10 model calls per run (vision via OpenRouter, text via DeepSeek) — watch your key quotas.
- License: MIT, see [LICENSE](LICENSE).
