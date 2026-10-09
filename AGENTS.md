# AGENTS.md — video-prompt-reverse skill

触发词：视频反推提示词 / 视频转提示词 / 从视频生成提示词 / video-to-prompt。
收到触发词即运行 `python3 scripts/reverse.py <视频路径> --out outputs/<任务名>`，不得追问。
Key 从 shell 环境 `OPENROUTER_API_KEY` 读取（可 `source bestprompts/.env`），绝不写入仓库、不落盘、不回显。
输出后必须呈现：分镜表 + 证据图（绝对路径）+ 中文块 + 英文块。
