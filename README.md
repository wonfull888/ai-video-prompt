# video-prompt-reverse

把一条参考视频反推成可直接拿去生成的中文 + 英文提示词。上传视频，拿回分镜、证据帧和双语 prompt。

## 适用人群

- 用 Cursor / Codex 做 AI 短剧、短视频、广告创意的创作者，想把刷到的参考视频变成自己的生成提示词。
- 典型场景：看到一段 15 秒的动漫酒馆戏，想用 Veo / Sora / Kling / 可灵复刻同款运镜和动作，直接反推一份 prompt 再改。

## 核心功能

- 完整视频分析链路：场景切分取证 → Gemini 直读视频初版分析 → 可疑动作多窗口稠密复查 → 表情独立审查 → 对账清洗 → 双语渲染。
- 中英双版 Markdown 默认输出：`prompt.md` 中文块在前、英文块在后，另附分开的 `prompt_zh.md` / `prompt_en.md`。
- 人物防串位：分镜里的人物自带身份名（如 `人物 P01（女招待）`），对账阶段锁定身份不许调换。
- 看不清就认：低证据画面（糊转场、小物件）强制写进不确定性，不编因果、不编台词。
- Cursor / Codex 快捷触发：说一句"视频反推提示词 + 视频路径"即跑。

## 效果展示

以下为真实测试输出（15.6s 动漫短片，`google/gemini-3.8-flash`）：开场 → 拿酒瓶 → 结尾独角。

![开场](docs/demo/frame-opening.png)
![拿酒瓶](docs/demo/frame-grab.png)
![结尾](docs/demo/frame-ending.png)

输出 `prompt.md` 节选（中文块）：

```text
### 镜头 S02 · 6.80–13.17s
机位／构图／运镜：中近景；平视；双人镜头；轻微推近
动作阶段 1 · 6.80–8.05s
  人物 P01（顾客）：动作：将右手伸向吧台上的酒瓶，握住它，并将其从吧台提起至胸口高度。
  人物 P02（店主）：动作：站在吧台后面，手放在黑色书本上。
```

## 安装说明

环境要求：Python 3.10+、`ffmpeg`（含 `ffprobe`）、一个 OpenRouter Key（视觉模型）和一个 DeepSeek Key（对账翻译）。

```bash
git clone https://github.com/wonfull888/video-prompt-reverse.git
cd video-prompt-reverse
export OPENROUTER_API_KEY=sk-or-...
export DEEPSEEK_API_KEY=sk-...
```

Key 只放环境变量，绝不进仓库（仓库内仅有 `.env.example` 给键名）。

## 使用方法

```bash
python3 scripts/reverse_full.py /path/to/video.mp4 --out outputs/demo
```

输入：一个 30 秒内的视频（mp4 / mov / webm）。输出目录里 `prompt.md` 就是成品，外加 `structured.json`（结构化数据）、`evidence_gallery.md`（证据图）、`shots.md`（分镜表）、`manifest.json`（模型与调用记录）。

## 注意事项与许可证

- 视频须在 30 秒内，超过会被拒绝；超大视频会自动压到 960p 以内再分析。
- 低码率视频的糊转场、小物件细节可能看不清，结果会如实标"不确定"，不保证和原片一字不差——这是反推规格，不是原 prompt。
- 费用：每次运行约 6–10 次模型调用（视觉走 OpenRouter，文字走 DeepSeek），注意 Key 额度。
- 开源许可证：MIT，见 [LICENSE](LICENSE)。
