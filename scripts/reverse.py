"""Video-to-prompt skill runner: BestPrompts PRO pipeline (single-pass) via OpenRouter gemini-3.8-flash."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

NEG_GROUPS = ["identity", "anatomy", "wardrobe_props", "environment",
              "motion_physics", "camera_editing", "rendering"]

ANALYSIS_PROMPT = """Analyze the ATTACHED ORIGINAL VIDEO FRAMES (in chronological order) plus metadata. Return JSON only, in English.
Count real edited shots, never action phases as shots. Within each shot, beats must cover the whole interval without gaps.
For each visible character give a stable ID (P01...). For each participant in each beat separate action, motion trajectory, directly VISIBLE expression, inferred emotion; use null when not reliably discernible. Never infer emotion from story alone.
Do not invent identities, brands, causes, focal lengths, dialogue, sound, CGI/VFX claims. If no clear narrative, story.summary describes visual progression without inventing plot.
All named fields required. JSON shape:
{"safety":"ok","story":{"summary":"","pacing":null},"global":{"category":null,"subject":"","mood":null,"characters":[{"id":"P01","role":"","appearance":null,"wardrobe":null,"props":[]}],"environment":"","depth_layers":null,"time_weather":null,"lighting":null,"color":null,"style":null,"continuity":[]},"shots":[{"id":"S01","start":0,"end":1,"shot_size":null,"camera_angle":null,"composition":null,"pov":null,"camera_motion":null,"opening_frame":null,"ending_frame":null,"transition":null,"confidence":0.8,"beats":[{"start":0,"end":1,"participants":[{"character_id":"P01","action":null,"motion":null,"visible_expression":null,"inferred_emotion":null,"confidence":0.8,"evidence_timestamps":[]}],"environment_change":null,"evidence_timestamps":[]}],"evidence_timestamps":[]}],"negative_constraints":{"identity":[],"anatomy":[],"wardrobe_props":[],"environment":[],"motion_physics":[],"camera_editing":[],"rendering":[]},"uncertainties":[]}.
Keep non-graphic content. Metadata: """

TRANSLATE_PREFIX = """Translate the following English values into natural Chinese. Preserve exact meaning, uncertainty, evidence level. Do not add facts. Return JSON only {"translations":{...}} with EXACTLY the same keys, each a nonempty Chinese string.\n"""

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

def probe(video: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,duration",
        "-show_entries", "format=duration,size", "-of", "json", str(video)],
        capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    s = d["streams"][0]
    num, den = s.get("avg_frame_rate", "30/1").split("/")
    fps = float(num) / float(den or 1)
    dur = float(s.get("duration") or d["format"]["duration"])
    w, hh = int(s["width"]), int(s["height"])
    return {"duration_seconds": round(dur, 3), "width": w, "height": hh,
            "fps": round(fps, 2), "aspect_ratio": f"{w}:{hh}",
            "sha256": sha256(video), "bytes": video.stat().st_size}

def extract_frames(video: Path, meta: dict, outdir: Path, n: int = 8) -> list[dict]:
    outdir.mkdir(parents=True, exist_ok=True)
    dur = meta["duration_seconds"]
    stamps = [round(dur * (i + 0.5) / n, 2) for i in range(n)]
    frames = []
    for i, t in enumerate(stamps):
        p = outdir / f"frame_{i+1:02d}_{t:.2f}s.png"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(t),
            "-i", str(video), "-frames:v", "1", str(p)], check=True)
        frames.append({"id": f"F{i+1:02d}", "timestamp": t, "path": str(p.resolve())})
    return frames

def call_openrouter(messages: list, max_tokens: int) -> tuple[str, dict]:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        sys.exit("Missing OPENROUTER_API_KEY (source bestprompts .env in shell, never copy the file).")
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("OPENROUTER_GEMINI_MODEL", "google/gemini-3.8-flash")
    provider = os.environ.get("OPENROUTER_GEMINI_PROVIDER", "google-ai-studio/flex")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if provider:
        payload["provider"] = {"order": [provider], "allow_fallbacks": False}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://bestprompts.app", "X-Title": "video-prompt-reverse-skill"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.load(r)
    except Exception as e:
        sys.exit(f"OpenRouter call failed: {e}")
    dt = round(time.time() - t0, 2)
    choice = raw["choices"][0]["message"]["content"]
    usage = raw.get("usage", {})
    return choice, {"model": raw.get("model", model), "seconds": dt, "usage": usage}

def strip_code_fence(t: str) -> str:
    t = t.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rsplit("```", 1)[0].strip():
            t = t.rsplit("```", 1)[0]
    return t.strip()

def collect_texts(v: dict) -> dict[str, str]:
    texts: dict[str, str] = {}
    def add(k: str, x: object):
        if isinstance(x, str) and x.strip():
            texts[k] = x
    add("story.summary", v["story"]["summary"]); add("story.pacing", v["story"]["pacing"])
    g = v["global"]
    for f in ("category", "subject", "mood", "environment", "depth_layers", "time_weather", "lighting", "color", "style"):
        add(f"global.{f}", g.get(f))
    for i, x in enumerate(g.get("continuity", [])): add(f"global.continuity.{i}", x)
    for c in g.get("characters", []):
        for f in ("role", "appearance", "wardrobe"): add(f"character.{c['id']}.{f}", c.get(f))
        for i, p in enumerate(c.get("props", [])): add(f"character.{c['id']}.props.{i}", p)
    for s in v.get("shots", []):
        for f in ("shot_size", "camera_angle", "composition", "pov", "camera_motion", "opening_frame", "ending_frame", "transition"):
            add(f"shot.{s['id']}.{f}", s.get(f))
        for i, b in enumerate(s.get("beats", [])):
            add(f"shot.{s['id']}.beat.{i}.environment_change", b.get("environment_change"))
            for p in b.get("participants", []):
                for f in ("action", "motion", "visible_expression", "inferred_emotion"):
                    add(f"shot.{s['id']}.beat.{i}.person.{p['character_id']}.{f}", p.get(f))
    for grp in NEG_GROUPS:
        for i, x in enumerate(v.get("negative_constraints", {}).get(grp, [])): add(f"negative.{grp}.{i}", x)
    for i, x in enumerate(v.get("uncertainties", [])): add(f"uncertainty.{i}", x)
    return texts

def render(v: dict, meta: dict, tr: dict, lang: str) -> tuple[str, str]:
    zh = lang == "zh"
    def T(k: str, fb: object) -> str:
        if not isinstance(fb, str) or not fb.strip(): return ""
        return tr.get(k, fb) if zh else (fb if isinstance(fb, str) else "")
    L = {"positive": "中文正面提示词", "negative": "中文负面提示词"} if zh else {"positive": "English Positive Prompt", "negative": "English Negative Prompt"}
    pos = [f"【{'剧情概述' if zh else 'Story'}】\n{T('story.summary', v['story']['summary'])}"]
    g = v["global"]
    pos.append(f"【{'全局设定' if zh else 'Global'}】\n{T('global.subject', g.get('subject'))} / {T('global.environment', g.get('environment'))} / {T('global.style', g.get('style'))}")
    for s in v["shots"]:
        key = f"shot.{s['id']}.camera_motion"
        cm = T(key, s.get("camera_motion"))
        rows = [f"{'镜头' if zh else 'Shot'} {s['id']} {s['start']:.2f}-{s['end']:.2f}s | {cm}"]
        for i, b in enumerate(s.get("beats", [])):
            for p in b.get("participants", []):
                ka = f"shot.{s['id']}.beat.{i}.person.{p['character_id']}.action"
                ke = f"shot.{s['id']}.beat.{i}.person.{p['character_id']}.visible_expression"
                rows.append(f"  {p['character_id']}: {T(ka, p.get('action'))} / {T(ke, p.get('visible_expression'))}")
        pos.append("\n".join(rows))
    neg_labels = {"identity": "身份", "anatomy": "肢体", "wardrobe_props": "服装道具", "environment": "环境",
                  "motion_physics": "运动物理", "camera_editing": "镜头剪辑", "rendering": "渲染"} if zh else \
                 {"identity": "Identity", "anatomy": "Anatomy", "wardrobe_props": "Wardrobe", "environment": "Environment",
                  "motion_physics": "Motion", "camera_editing": "Camera", "rendering": "Rendering"}
    neg = []
    for grp in NEG_GROUPS:
        vals = [T(f"negative.{grp}.{i}", x) for i, x in enumerate(v["negative_constraints"].get(grp, [])) if T(f"negative.{grp}.{i}", x)]
        if vals: neg.append(f"{neg_labels[grp]}: " + "; ".join(vals))
    return "\n\n".join(pos), "\n".join(neg) or ("无特定负面约束。" if zh else "No specific negative constraints.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="outputs/result")
    ap.add_argument("--frames", type=int, default=8)
    a = ap.parse_args()
    video = Path(a.video).expanduser()
    out = Path(a.out); (out / "frames").mkdir(parents=True, exist_ok=True)
    meta = probe(video)
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    frames = extract_frames(video, meta, out / "frames", a.frames)
    parts: list = [{"type": "text", "text": ANALYSIS_PROMPT + json.dumps({k: v for k, v in meta.items() if k != 'sha256'}) + f" sha256={meta['sha256'][:16]}"}]
    for f in frames:
        parts.append({"type": "text", "text": f"Frame {f['id']} at {f['timestamp']}s"})
        parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(open(f['path'], 'rb').read()).decode()}})
    content, call1 = call_openrouter([{"role": "user", "content": parts}], 8000)
    analysis = json.loads(strip_code_fence(content))
    if analysis.get("safety") != "ok":
        sys.exit("Model refused analysis.")
    texts = collect_texts(analysis)
    content2, call2 = call_openrouter([{"role": "user", "content": TRANSLATE_PREFIX + json.dumps(texts, ensure_ascii=False)}], 8000)
    translations = json.loads(strip_code_fence(content2)).get("translations", {})
    zh_pos, zh_neg = render(analysis, meta, translations, "zh")
    en_pos, en_neg = render(analysis, meta, translations, "en")
    (out / "prompt_zh.txt").write_text(f"中文正面提示词\n\n{zh_pos}\n\n中文负面提示词\n\n{zh_neg}\n", encoding="utf-8")
    (out / "prompt_en.txt").write_text(f"English Positive Prompt\n\n{en_pos}\n\nEnglish Negative Prompt\n\n{en_neg}\n", encoding="utf-8")
    (out / "structured.json").write_text(json.dumps({"source": meta, "analysis": analysis, "translations": translations}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "evidence_gallery.md").write_text("\n\n".join(f"{f['id']} {f['timestamp']}s\n\n![{f['id']}]({f['path']})" for f in frames) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"model": call1["model"], "calls": [call1, call2], "frames": frames}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK -> {out.resolve()}")

if __name__ == "__main__":
    main()
