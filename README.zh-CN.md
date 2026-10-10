# ai-video-prompt

[English](README.md) | 中文版（翻译）

给它一条参考视频，拿回一份最大程度还原的提示词——简单改改就能拿去生成。你会得到分镜（shot：视频被剪成的镜头段落）、证据帧和双语 prompt 文件。

## 适用人群

- 在 Cursor / Codex 里做 AI 视频（短剧、短片、广告）的人：刷到一条参考片，想复刻它的运镜、动作和氛围。
- 在 code agent 里说一句"视频反推提示词 + 视频路径"，剩下的看和写都由 skill 代劳。

## 核心功能

- 视觉模型（vision model）看完整视频，而不只是截图：切镜头、跟动作、记运镜、看表情，这是核心活，由 `google/gemini-3.8-flash`（走 OpenRouter）干。Gemini 是唯一能直接读视频文件的主流模型（OpenAI 和 Claude 只收图片，视频得先拆成帧），流水线建在它上面就是这个原因。
- 文字模型（DeepSeek，可换）当审核：把容易看错的动作段逐帧复查，证据站不住的删掉，再翻成中文。
- 默认输出中英双版 Markdown：`prompt.md` 中文在前、英文在后，另附 `prompt_zh.md` / `prompt_en.md`。
- 人物不串位：每个动作阶段都带身份名（如`人物 P01（女招待）`），对账阶段锁定身份不许调换。
- 适配你真正拿来生成的模型：Seedance 2.5 / 2.0、Veo、Sora、Kling、Wan 和通用版，见 `references/model-adapters.md`。

为什么不用 code agent 自带的模型？两个原因：流水线要把原始视频 + 几十帧按固定流程调好几次 API、用自己的 Key，这塞不进聊天上下文；而且"看"（Gemini）和"审核翻译"（DeepSeek）分开，各自便宜又稳定。你的 agent 只管一句话唤起 skill。

## 效果展示

真实测试输出（27 秒奇幻战斗混剪，`google/gemini-3.8-flash`）：开场 → 关键动作 → 结尾。

![开场](docs/demo/frame-opening.png)
![关键动作](docs/demo/frame-grab.png)
![结尾](docs/demo/frame-ending.png)

输出 `prompt.md` 节选（中文块）：

```text
### 镜头 S01 · 0.00–1.20s
机位／构图／运镜：中景镜头；低角度；动态水平构图；向右跟踪
动作阶段 1 · 0.00–1.20s
  人物 P01（主角）：动作：在草地上滑行，同时挥舞燃烧的巨剑劈砍暗影恶魔；运动：向右滑行
```

## 安装说明

环境要求：Python 3.10+、`ffmpeg`（含 `ffprobe`）、一个 OpenRouter Key（视觉模型）和一个 DeepSeek Key（审核翻译）。

```bash
git clone https://github.com/wonfull888/ai-video-prompt.git
cd ai-video-prompt
export OPENROUTER_API_KEY=sk-or-...
export DEEPSEEK_API_KEY=sk-...
```

Key 只放环境变量，绝不进仓库（仓库内仅有 `.env.example` 给键名）。

## 使用方法

在你的 code agent（Cursor / Codex）里说一句就行：

```text
视频反推提示词 /path/to/video.mp4
```

agent 会唤起本 skill 并跑完流水线。底下实际就一条命令（输入：一个 30 秒内的视频，mp4 / mov / webm）：

```bash
python3 scripts/reverse_full.py /path/to/video.mp4 --out outputs/demo
```

输出目录里 `prompt.md` 就是成品，外加 `structured.json`（结构化数据）、`evidence_gallery.md`（证据图）、`shots.md`（分镜表）、`manifest.json`（模型与调用记录）。

## 注意事项与许可证

- 默认最长 30 秒；想放宽自己改 `scripts/reverse_full.py` 里 `probe_video` 的时长限制（片子越长调用次数越多）。
- 生成视频都是真金白银：使用前自己过一遍 prompt，把人名细节改成你项目的，反推的是还原参考，不是为你项目定制的。
- 费用：每次运行约 6–10 次模型调用（视觉走 OpenRouter，文字走 DeepSeek），注意 Key 额度。
- 开源许可证：MIT，见 [LICENSE](LICENSE)。
- Fork 自 [LunarXuan/video-prompt-reverse](https://github.com/LunarXuan/video-prompt-reverse)——skill 框架和模型适配器来自该项目，BestPrompts PRO 分析流水线是后加上去的。
