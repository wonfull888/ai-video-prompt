"""Full BestPrompts PRO pipeline as a shareable skill script (no secrets in repo).

Stages (mirrors bestprompts bp/pro.py run_pro):
probe -> prepare(scene detect) -> analysis(video+frames, gemini) -> validate
-> focus window -> motion_review(dense) -> expression_review(orig-res sparse)
-> reconcile -> clean/causal_cleanup -> story -> translate(+missing)
-> render_pro zh/en -> artifacts.
Vision calls use OpenRouter gemini-3.8-flash; compiler calls use DeepSeek.
Keys come from environment only.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, math, os, re, subprocess, sys, time
from pathlib import Path
import urllib.request

NEGATIVE_GROUPS = ("identity", "anatomy", "wardrobe_props", "environment",
                   "motion_physics", "camera_editing", "rendering")

PRO_ANALYSIS = """Analyze the ORIGINAL VIDEO, not a prior prompt. Return JSON only, in English.
Video is primary evidence. Optional user text is unverified context: use it to locate details, but do
not turn its claims into observed facts. Count real edited shots, never action phases as shots.
Within each shot, beats must cover the whole interval without gaps. Give each visible character a
stable ID. For EACH relevant character in EACH beat, separate action, motion trajectory, directly
VISIBLE expression (eyes, mouth, gaze, face), and inferred emotion. Use null when face/emotion is
not reliably discernible. Never infer emotion solely from story, or a spoken line from an open mouth.
Use null for other unobservable optional values. Do not invent identities, brands, causes, focal
lengths, effects, dialogue or sound. Audio has not been verified; do not describe it. If there is no
clear narrative, story.summary should describe visual progression without inventing a plot.
Negative constraints may prevent generation artifacts, but must NEVER negate an observed source
action, imply an unsupported cause, or assume CGI/VFX or other production methods.
All named fields are required, though nullable fields may be null. JSON shape:
{"safety":"ok|blocked","story":{"summary":"","pacing":null},
"global":{"category":null,"subject":"","mood":null,"characters":[{"id":"P01",
"role":"","appearance":null,"wardrobe":null,"props":[]}],"environment":"",
"depth_layers":null,"time_weather":null,"lighting":null,"color":null,"style":null,
"continuity":[]},"shots":[{"id":"S01","start":0,"end":1,"shot_size":null,
"camera_angle":null,"composition":null,"pov":null,"camera_motion":null,
"opening_frame":null,"ending_frame":null,"transition":null,"confidence":0.8,
"beats":[{"start":0,"end":1,"participants":[{"character_id":"P01","action":null,
"motion":null,"visible_expression":null,"inferred_emotion":null,"confidence":0.8,
"evidence_timestamps":[]}],"environment_change":null,"evidence_timestamps":[]}],
"evidence_timestamps":[]}],"negative_constraints":{"identity":[],"anatomy":[],
"wardrobe_props":[],"environment":[],"motion_physics":[],"camera_editing":[],
"rendering":[]},"uncertainties":[]}.
Use measurable times, evidence timestamps, and conservative uncertainties. Keep non-graphic content.
"""

LABELS = {
    "zh": {"positive": "中文正面提示词", "negative": "中文负面提示词",
           "story": "剧情概述", "spec": "视频规格", "global": "全局设定", "characters": "人物与道具",
           "scene": "场景与风格", "shot": "镜头", "beat": "动作阶段", "continuity": "连续性",
           "uncertainties": "证据边界与不确定性", "actor": "人物", "action": "动作",
           "motion": "运动", "expression": "可见表情", "emotion": "情绪变化", "environment_change": "环境变化",
           "camera": "机位／构图／运镜", "opening": "起始画面", "ending": "结束画面",
           "transition": "转场", "lighting": "光线", "color": "色彩", "style": "风格",
           "mood": "整体氛围", "pacing": "叙事节奏", "negative_groups": {
               "identity": "身份", "anatomy": "肢体", "wardrobe_props": "服装与道具",
               "environment": "环境", "motion_physics": "运动与物理", "camera_editing": "镜头与剪辑",
               "rendering": "画质与渲染"}},
    "en": {"positive": "English Positive Prompt", "negative": "English Negative Prompt",
           "story": "Story", "spec": "Video format", "global": "Global setup", "characters": "Characters and props",
           "scene": "Setting and look", "shot": "Shot", "beat": "Action beat", "continuity": "Continuity",
           "uncertainties": "Evidence limits and uncertainties", "actor": "Character", "action": "Action",
           "motion": "Motion", "expression": "Visible expression", "emotion": "Emotion change",
           "environment_change": "Environment change", "camera": "Angle / composition / movement",
           "opening": "Opening frame", "ending": "Ending frame", "transition": "Transition",
           "lighting": "Lighting", "color": "Color", "style": "Style", "mood": "Overall mood",
           "pacing": "Pacing", "negative_groups": {
               "identity": "Identity", "anatomy": "Anatomy", "wardrobe_props": "Wardrobe and props",
               "environment": "Environment", "motion_physics": "Motion and physics",
               "camera_editing": "Camera and editing", "rendering": "Rendering"}},
}

UNSUPPORTED_CAUSE = re.compile(r"\b(strik|struck|hit|trip|tackl|knock|collid|caus)\w*\b", re.I)
PRODUCTION_CLAIM = re.compile(r"\b(CGI|VFX|visual effects|digital composit\w*|deepfake|face.?swap)\b", re.I)
EMOTIONAL_ADVERB = re.compile(r"\b(cheerfully|happily|proudly|angrily|sadly|fearfully|determinedly)\b", re.I)
CAUSAL_WORDS = re.compile(r"\b(knock|collid|push|pull|trip|tackle|hit|cause|throw|fall|fell|retrieve|grab|snatch)\w*\b", re.I)


def digest(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

def wjson(p: Path, o) -> None:
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")

def run(args: list[str]) -> str:
    r = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise ValueError(f"{args[0]} failed: {r.stderr[-800:]}")
    return r.stdout + r.stderr

def parse_json(t: str) -> dict:
    t = t.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if "```" in t:
            t = t.rsplit("```", 1)[0]
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        raise ValueError("No JSON object in model output")
    return json.loads(m.group(0))

def extract_frame(video: Path, d: Path, label: str, ts: float):
    for off in (0.0, .1, .25, .5):
        actual = round(max(0.0, ts - off), 3)
        p = d / f"{label}-{actual:.3f}.png"
        run(["ffmpeg", "-v", "error", "-ss", str(actual), "-i", str(video),
             "-frames:v", "1", "-c:v", "png", str(p)])
        if p.exists() and p.stat().st_size:
            return p, actual
    raise ValueError(f"No decodable frame near {ts:.3f}s")

def probe_video(video: Path) -> dict:
    if video.stat().st_size > 100_000_000:
        raise ValueError("Video exceeds 100 MB")
    pr = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)]))
    st = next((s for s in pr["streams"] if s["codec_type"] == "video"), None)
    if not st:
        raise ValueError("No video stream")
    dur = float(pr["format"]["duration"])
    if not math.isfinite(dur) or not 0 < dur <= 30:
        raise ValueError("Video duration must be within 30 seconds")
    n, dn = map(float, st["r_frame_rate"].split("/"))
    w, hh = st["width"], st["height"]
    g = math.gcd(w, hh)
    return {"path": str(video), "sha256": digest(video), "duration_seconds": dur,
            "width": w, "height": hh, "fps": n / dn,
            "aspect_ratio": f"{w//g}:{hh//g}",
            "has_audio": any(s["codec_type"] == "audio" for s in pr["streams"])}

def prepare(video: Path, d: Path, facts: dict) -> dict:
    dur = facts["duration_seconds"]
    regular = [round(max(0.0, dur - .08) * n / 11, 3) for n in range(12)]
    cuts: list[float] = []
    thresh = .35
    for th in (.18, .26, .35, .5):
        text = run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf",
                    f"select='gt(scene,{th})',showinfo", "-an", "-f", "null", "-"])
        cuts = sorted(set(float(v) for v in re.findall(r"pts_time:([\d.]+)", text)))
        stamps = sorted(set(regular + [round(max(0, c - .04), 3) for c in cuts] + [round(c, 3) for c in cuts]))
        if len(stamps) <= 60:
            thresh = th
            break
    if len(stamps) > 60:
        raise ValueError("Too many scene candidates")
    fr = d / "evidence_frames"
    fr.mkdir(parents=True, exist_ok=True)
    ev = []
    for i, s in enumerate(stamps):
        p, a = extract_frame(video, fr, f"E{i+1:02d}", s)
        ev.append({"id": f"E{i+1:02d}", "timestamp": a, "path": str(p.resolve()), "sha256": digest(p)})
    src = {**facts, "cut_candidates": cuts, "scene_threshold": thresh,
           "sampling_timestamps": [f["timestamp"] for f in ev], "visual_evidence": ev}
    wjson(d / "source.json", src)
    return src

def data_url(p: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

def frame_parts(src: dict) -> list:
    parts = []
    for f in src["visual_evidence"]:
        parts += [{"type": "text", "text": f"Original frame at {f['timestamp']} seconds"},
                  {"type": "image_url", "image_url": {"url": data_url(Path(f["path"]), "image/png")}}]
    return parts

class Client:
    def __init__(self, d: Path):
        self.d = d
        self.calls: list[dict] = []
        self.stage: str | None = None

    def call(self, stage: str, content, compiler=False, max_tokens=6500) -> dict:
        self.stage = stage
        if compiler:
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            model = os.environ.get("VIDEO_BLUEPRINT_DEEPSEEK_MODEL", "deepseek-v4-flash")
        else:
            key = os.environ.get("OPENROUTER_API_KEY", "")
            base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            model = os.environ.get("OPENROUTER_GEMINI_MODEL", "google/gemini-3.8-flash")
        if not key:
            sys.exit(f"Missing API key for {stage}")
        payload: dict = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}
        if compiler:
            payload.update({"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}})
            prov = "deepseek"
        else:
            prov = os.environ.get("OPENROUTER_GEMINI_PROVIDER", "google-ai-studio/flex")
            payload.update({"provider": {"order": [prov], "allow_fallbacks": False}})
        t0 = time.monotonic()
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://bestprompts.app", "X-Title": "video-prompt-reverse-skill"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = json.load(r)
        except Exception as e:
            self.calls.append({"stage": stage, "status": "failed", "error": str(e)[:200]})
            raise
        dt = round(time.monotonic() - t0, 2)
        self.calls.append({"stage": stage, "model": raw.get("model", model), "provider": prov,
                           "seconds": dt, "usage": raw.get("usage", {}), "status": "returned"})
        wjson(self.d / "calls.json", self.calls)
        wjson(self.d / f"{stage}.response.json", raw)
        choice = raw["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("Truncated model output")
        print(f"[{stage}] {dt}s model={raw.get('model', model)}", flush=True)
        return parse_json(choice["message"]["content"])

def _num(v) -> float:
    n = float(v)
    if not math.isfinite(n):
        raise ValueError("Non-finite timestamp")
    return n

def validate_pro(v: dict, dur: float) -> None:
    if v.get("safety") != "ok":
        raise ValueError("PRO analysis blocked or safety field missing")
    if not isinstance(v.get("story"), dict) or not str(v["story"].get("summary") or "").strip():
        raise ValueError("Missing story / visual progression")
    if "pacing" not in v["story"]:
        raise ValueError("Missing story.pacing")
    g = v.get("global")
    need = ("category", "subject", "mood", "characters", "environment", "depth_layers",
            "time_weather", "lighting", "color", "style", "continuity")
    if not isinstance(g, dict) or any(k not in g for k in need):
        raise ValueError("Incomplete global structure")
    ids = set()
    for c in g["characters"]:
        if any(k not in c for k in ("id", "role", "appearance", "wardrobe", "props")) or not isinstance(c["props"], list):
            raise ValueError("Incomplete character")
        if not c["id"] or c["id"] in ids:
            raise ValueError("Duplicate/empty character ID")
        ids.add(c["id"])
    shots = v.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("Missing shots")
    cur = 0.0
    for i, s in enumerate(shots, 1):
        req = ("id", "start", "end", "shot_size", "camera_angle", "composition", "pov",
               "camera_motion", "opening_frame", "ending_frame", "transition", "confidence",
               "beats", "evidence_timestamps")
        if any(k not in s for k in req) or s["id"] != f"S{i:02d}":
            raise ValueError("Incomplete/invalid shot structure")
        a, b = _num(s["start"]), _num(s["end"])
        if abs(a - cur) > .15 or b <= a or b > dur + .15 or not 0 <= _num(s["confidence"]) <= 1:
            raise ValueError("Invalid shot timeline/confidence")
        bc = a
        for beat in s["beats"]:
            if any(k not in beat for k in ("start", "end", "participants", "environment_change", "evidence_timestamps")):
                raise ValueError("Incomplete beat")
            x, y = _num(beat["start"]), _num(beat["end"])
            if abs(x - bc) > .15 or y <= x or y > b + .15:
                raise ValueError("Invalid/gapped beat timeline")
            for p in beat["participants"]:
                f = ("character_id", "action", "motion", "visible_expression", "inferred_emotion",
                     "confidence", "evidence_timestamps")
                if any(k not in p for k in f) or p["character_id"] not in ids:
                    raise ValueError("Incomplete/unknown beat participant")
            if not beat["participants"] and not beat["environment_change"]:
                raise ValueError("Empty beat content")
            bc = y
        if abs(bc - b) > .15:
            raise ValueError("Beat timeline does not cover shot")
        cur = b
    if abs(cur - dur) > .15:
        raise ValueError("Shots do not cover video")
    ng = v.get("negative_constraints")
    if not isinstance(ng, dict) or any(not isinstance(ng.get(k), list) for k in NEGATIVE_GROUPS):
        raise ValueError("Incomplete negative constraint groups")
    if not isinstance(v.get("uncertainties"), list):
        raise ValueError("Missing uncertainties")

def _expr_id(desc: str, chars: list[dict]):
    text = desc.lower()
    for group in (("woman", "mother", "female", "lady"), ("baby", "child", "toddler", "infant"),
                  ("man", "male", "thief", "adult male")):
        if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in group):
            m = [c["id"] for c in chars if any(
                re.search(r"\b" + re.escape(w) + r"\b", (str(c["role"]) + " " + str(c["appearance"])).lower())
                for w in group)]
            return m[0] if len(m) == 1 else None
    toks = set(re.findall(r"[a-z]{3,}", text)) - {"the", "with", "and", "individual", "person", "figure"}
    sc = []
    for c in chars:
        d = " ".join(str(c.get(k) or "") for k in ("role", "appearance", "wardrobe"))
        sc.append((len(toks & set(re.findall(r"[a-z]{3,}", d.lower()))), c["id"]))
    sc.sort(reverse=True)
    if sc and sc[0][0] >= 2 and (len(sc) == 1 or sc[0][0] > sc[1][0]):
        return sc[0][1]
    return None

def clean_analysis(v: dict, fs: float, fe: float, confirmed: bool, expr: dict | None = None) -> dict:
    by_id: dict[str, list[dict]] = {}
    if expr:
        for it in expr.get("person_expressions", []):
            cid = _expr_id(it.get("person_description", ""), v["global"]["characters"])
            if cid:
                by_id.setdefault(cid, []).append(it)
    for s in v["shots"]:
        for b in s["beats"]:
            for p in b["participants"]:
                if isinstance(p.get("action"), str):
                    p["action"] = re.sub(r"\s{2,}", " ", EMOTIONAL_ADVERB.sub("", p["action"])).strip()
                if expr is not None:
                    sup = [it for it in by_id.get(p["character_id"], [])
                           if float(it.get("start", 0)) <= float(b["start"]) + .15
                           and float(it.get("end", 0)) >= float(b["end"]) - .15
                           and it.get("visible_expression")]
                    if sup:
                        p["visible_expression"] = sup[0]["visible_expression"]
                        p["inferred_emotion"] = sup[0].get("inferred_emotion")
                    else:
                        p["visible_expression"] = None
                        p["inferred_emotion"] = None
                e = p.get("visible_expression")
                if isinstance(e, str) and e.strip().lower().strip(" .") in ("unknown", "not visible", "unclear", "n/a"):
                    p["visible_expression"] = None
                if not p.get("visible_expression"):
                    p["inferred_emotion"] = None
    for grp in NEGATIVE_GROUPS:
        v["negative_constraints"][grp] = [x for x in v["negative_constraints"][grp]
            if isinstance(x, str) and not UNSUPPORTED_CAUSE.search(x) and not PRODUCTION_CLAIM.search(x)]
    if not any(v["negative_constraints"][g] for g in NEGATIVE_GROUPS):
        v["negative_constraints"].update({
            "anatomy": ["extra or distorted limbs and hands"],
            "wardrobe_props": ["unmotivated wardrobe or prop changes"],
            "motion_physics": ["teleporting subjects or objects"],
            "camera_editing": ["unmotivated cuts or camera movement"],
            "rendering": ["flicker, ghosting, and visible rendering artifacts"]})
    if not confirmed and causal_claims(v, fs, fe):
        raise ValueError("Unsupported causal action survived focused review")
    return v

def causal_claims(v: dict, a: float, b: float) -> dict[str, str]:
    slots = {"story.summary": v["story"]["summary"], "global.subject": v["global"]["subject"]}
    for si, s in enumerate(v["shots"]):
        for bi, beat in enumerate(s["beats"]):
            if beat["start"] < b and beat["end"] > a:
                for pi, p in enumerate(beat["participants"]):
                    slots[f"shots.{si}.beats.{bi}.participants.{pi}.action"] = p.get("action") or ""
    return {k: t for k, t in slots.items() if UNSUPPORTED_CAUSE.search(t or "")}

def neutralize(client: Client, v: dict, motion: dict, a: float, b: float) -> None:
    claims = causal_claims(v, a, b)
    if not claims:
        return
    r = client.call("causal_cleanup", "The reviewed images do not establish these specific causal links. Rewrite ONLY the listed strings as observable before/after or simultaneous events. Preserve all visible energy, action, timing and subjects; do not erase the spectacle. Do not use hit/strike/trip/tackle/knock/collide/cause. Return JSON only: {\"replacements\":{same.path.keys:replacement.string}}.\n" + json.dumps({"claims": claims, "motion_observations": motion["observations"]}, ensure_ascii=False), compiler=True, max_tokens=3000)
    rep = r.get("replacements")
    if not isinstance(rep, dict) or set(rep) != set(claims):
        raise ValueError("Incomplete causality cleanup")
    for path, val in rep.items():
        if not isinstance(val, str) or not val.strip() or UNSUPPORTED_CAUSE.search(val):
            raise ValueError("Causality cleanup still asserts unsupported cause")
        if path == "story.summary":
            v["story"]["summary"] = val
        elif path == "global.subject":
            v["global"]["subject"] = val
        else:
            q = path.split(".")
            v["shots"][int(q[1])]["beats"][int(q[3])]["participants"][int(q[5])]["action"] = val

def focus_window_pro(v: dict, dur: float, top_n: int = 3):
    """Top-N non-overlapping high-risk motion intervals (generic, not per-video)."""
    proxy = {"shots": [{"actions": [{"start": b["start"], "end": b["end"],
        "description": " ".join(str(p.get("action") or "") + " " + str(p.get("motion") or "") for p in b["participants"])}
        for b in s["beats"]]} for s in v["shots"]]}
    acts = [x for s in proxy["shots"] for x in s["actions"]]
    ranked = sorted(
        ((len(CAUSAL_WORDS.findall(x["description"])), float(x["end"]) - float(x["start"]), i, x)
         for i, x in enumerate(acts)),
        key=lambda t: (t[0], t[1], t[2]), reverse=True)
    wins: list[tuple[float, float]] = []
    for _, _, _, act in ranked:
        if len(wins) >= top_n:
            break
        a = max(0.0, float(act["start"]) - .75)
        b = min(dur, float(act["end"]) + .25)
        if b - a > 4.0:
            b = min(dur, a + 4.0)
        a, b = round(a, 3), round(b, 3)
        if all(b <= w[0] + .3 or a >= w[1] - .3 for w in wins):
            wins.append((a, b))
    wins.sort()
    return wins or [(0.0, min(dur, 4.0))]

def focused_frames(video: Path, d: Path, a: float, b: float) -> list[dict]:
    fd = d / "focus_frames"
    fd.mkdir(parents=True, exist_ok=True)
    n = min(17, max(5, math.ceil((b - a) / .25) + 1))
    out = []
    for i in range(n):
        s = round(a + (b - a) * i / (n - 1), 3)
        p, act = extract_frame(video, fd, f"F{i+1:02d}", s)
        out.append({"timestamp": act, "path": str(p.resolve()), "sha256": digest(p)})
    wjson(d / "focus_frames.json", out)
    return out

def select_frames(src: dict, analysis: dict, limit=12) -> list[dict]:
    shots = analysis["shots"]
    if len(shots) > limit:
        shots = [shots[round(i * (len(shots) - 1) / (limit - 1))] for i in range(limit)]
    frames = src["visual_evidence"]
    sel = []
    for s in shots:
        mid = (float(s["start"]) + float(s["end"])) / 2
        opts = [f for f in frames if float(s["start"]) <= f["timestamp"] <= float(s["end"])]
        if opts:
            c = min(opts, key=lambda f: abs(f["timestamp"] - mid))
            if c not in sel:
                sel.append(c)
    if len(sel) < min(limit, len(frames)):
        for f in (frames[0], frames[-1]):
            if len(sel) < limit and f not in sel:
                sel.append(f)
    return sorted(sel, key=lambda f: f["timestamp"])

def collect_texts(v: dict) -> dict[str, str]:
    t: dict[str, str] = {}
    def add(k: str, x):
        if isinstance(x, str) and x.strip():
            t[k] = x
    add("story.summary", v["story"]["summary"]); add("story.pacing", v["story"]["pacing"])
    g = v["global"]
    for f in ("category", "subject", "mood", "environment", "depth_layers", "time_weather", "lighting", "color", "style"):
        add(f"global.{f}", g.get(f))
    for i, x in enumerate(g.get("continuity", [])):
        add(f"global.continuity.{i}", x)
    for c in g.get("characters", []):
        for f in ("role", "appearance", "wardrobe"):
            add(f"character.{c['id']}.{f}", c.get(f))
        for i, p in enumerate(c.get("props", [])):
            add(f"character.{c['id']}.props.{i}", p)
    for s in v.get("shots", []):
        for f in ("shot_size", "camera_angle", "composition", "pov", "camera_motion", "opening_frame", "ending_frame", "transition"):
            add(f"shot.{s['id']}.{f}", s.get(f))
        for i, b in enumerate(s.get("beats", [])):
            add(f"shot.{s['id']}.beat.{i}.environment_change", b.get("environment_change"))
            for p in b.get("participants", []):
                for f in ("action", "motion", "visible_expression", "inferred_emotion"):
                    add(f"shot.{s['id']}.beat.{i}.person.{p['character_id']}.{f}", p.get(f))
    for grp in NEGATIVE_GROUPS:
        for i, x in enumerate(v.get("negative_constraints", {}).get(grp, [])):
            add(f"negative.{grp}.{i}", x)
    for i, x in enumerate(v.get("uncertainties", [])):
        add(f"uncertainty.{i}", x)
    return t

def render_pro(v: dict, src: dict, tr: dict, lang: str):
    L = LABELS[lang]
    zh = lang == "zh"
    def T(k: str, fb) -> str:
        if not isinstance(fb, str) or not fb.strip():
            return ""
        return tr.get(k, fb) if zh else fb
    def line(lbl: str, c: str):
        return f"{lbl}：{c}" if c else None
    def sec(name: str, rows) -> str:
        return "\n".join([f"【{name}】"] + [r for r in rows if r])
    g = v["global"]
    pos = [sec(L["story"], [T("story.summary", v["story"]["summary"]), line(L["pacing"], T("story.pacing", v["story"]["pacing"]))]),
           sec(L["spec"], [f"{src['aspect_ratio']} · {src['duration_seconds']:.2f}s · {src['width']}×{src['height']}"]),
           sec(L["global"], [T(f"global.{f}", g.get(f)) for f in ("category", "subject", "mood")])]
    ppl = []
    for c in g["characters"]:
        det = [T(f"character.{c['id']}.{f}", c.get(f)) for f in ("role", "appearance", "wardrobe")]
        det += [T(f"character.{c['id']}.props.{i}", p) for i, p in enumerate(c.get("props", []))]
        ppl.append(f"{c['id']}：" + "；".join(x for x in det if x))
    if ppl:
        pos.append(sec(L["characters"], ppl))
    sc = [T(f"global.{f}", g.get(f)) for f in ("environment", "depth_layers", "time_weather")]
    sc += [line(L["lighting"], T("global.lighting", g.get("lighting"))),
           line(L["color"], T("global.color", g.get("color"))),
           line(L["style"], T("global.style", g.get("style")))]
    pos.append(sec(L["scene"], sc))
    for s in v["shots"]:
        cam = [T(f"shot.{s['id']}.{f}", s.get(f)) for f in ("shot_size", "camera_angle", "composition", "pov", "camera_motion")]
        rows = [line(L["camera"], "；".join(x for x in cam if x)),
                line(L["opening"], T(f"shot.{s['id']}.opening_frame", s.get("opening_frame")))]
        for i, b in enumerate(s.get("beats", [])):
            rows.append(f"{L['beat']} {i+1} · {b['start']:.2f}–{b['end']:.2f}s")
            for p in b.get("participants", []):
                det = [line(L[lbl], T(f"shot.{s['id']}.beat.{i}.person.{p['character_id']}.{f}", p.get(f)))
                       for lbl, f in (("action", "action"), ("motion", "motion"),
                                       ("expression", "visible_expression"), ("emotion", "inferred_emotion"))]
                rows.append(f"  {L['actor']} {p['character_id']}：" + "；".join(x for x in det if x))
            ch = T(f"shot.{s['id']}.beat.{i}.environment_change", b.get("environment_change"))
            if ch:
                rows.append(f"  {L['environment_change']}：{ch}")
        rows += [line(L["ending"], T(f"shot.{s['id']}.ending_frame", s.get("ending_frame"))),
                 line(L["transition"], T(f"shot.{s['id']}.transition", s.get("transition")))]
        pos.append(sec(f"{L['shot']} {s['id']} · {s['start']:.2f}–{s['end']:.2f}s", rows))
    cont = [T(f"global.continuity.{i}", x) for i, x in enumerate(g.get("continuity", []))]
    if cont:
        pos.append(sec(L["continuity"], cont))
    un = [T(f"uncertainty.{i}", x) for i, x in enumerate(v.get("uncertainties", []))]
    if un:
        pos.append(sec(L["uncertainties"], un))
    neg = []
    for grp in NEGATIVE_GROUPS:
        vals = [T(f"negative.{grp}.{i}", x) for i, x in enumerate(v.get("negative_constraints", {}).get(grp, []))]
        vals = [x for x in vals if x]
        if vals:
            neg.append(f"{L['negative_groups'][grp]}：" + "；".join(vals))
    if not neg:
        neg.append("无特定负面约束。" if zh else "No specific negative constraints.")
    return "\n\n".join(pos), "\n".join(neg)

def render_markdown(p: dict, lang: str) -> str:
    title = "视频反推 Prompt" if lang == "zh" else "Video-to-Prompt"
    ph = "正面提示词" if lang == "zh" else "Positive prompt"
    nh = "负面约束" if lang == "zh" else "Negative constraints"
    pos = re.sub(r"(?m)^【([^】]+)】$", r"### \1", p[f"{lang}_positive"].strip())
    negs = [f"- {l.strip()}" for l in p[f"{lang}_negative"].splitlines() if l.strip()]
    return f"# {title}\n\n## {ph}\n\n{pos}\n\n## {nh}\n\n" + "\n".join(negs) + "\n"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="outputs/result-full")
    a = ap.parse_args()
    video = Path(a.video).expanduser()
    out = Path(a.out)
    prodir = out / "pro-gemini"
    prodir.mkdir(parents=True, exist_ok=True)
    client = Client(prodir)
    facts = probe_video(video)
    print(json.dumps({k: v for k, v in facts.items() if k != "path"}, ensure_ascii=False), flush=True)
    src = prepare(video, prodir, facts)
    print(f"evidence frames: {len(src['visual_evidence'])}, cuts: {src['cut_candidates']}", flush=True)
    mime = {".mp4": "video/mp4", ".mov": "video/mov", ".webm": "video/webm"}.get(video.suffix.lower())
    if not mime:
        sys.exit("Unsupported video container")
    meta = {k: v for k, v in src.items() if k not in ("path", "visual_evidence")}
    initial = client.call("analysis",
        [{"type": "text", "text": PRO_ANALYSIS + "\nSource metadata: " + json.dumps(meta)},
         {"type": "video_url", "video_url": {"url": data_url(video, mime)}}], max_tokens=10000)
    validate_pro(initial, src["duration_seconds"])
    wjson(prodir / "analysis.initial.json", initial)
    fs_list = focus_window_pro(initial, src["duration_seconds"])
    print(f"focus windows: {fs_list}", flush=True)
    motions: list[dict] = []
    for wi, (fs, fe) in enumerate(fs_list):
        dense = focused_frames(video, prodir / f"focus_{wi}", fs, fe)
        mr = [{"type": "text", "text": "Independently inspect these ORDERED dense original video frames ONLY. Do not infer from a prior narrative. Focus on exact direction of motion, who carries what, whether a body/object visibly contacts another, and what visibly precedes a fall or change of direction. If contact or a causal mechanism is not directly visible, mark causal_link='unconfirmed' and supported_causal_action=null. Temporal sequence alone never proves causation. Return JSON only: {\"observations\":[{\"timestamp\":number,\"description\":string}],\"contact\":\"observed|not_observed|unclear\",\"causal_link\":\"observed|unconfirmed\",\"supported_causal_action\":null,\"uncertainties\":[string]}. Video seconds " + str(fs) + "–" + str(fe) + "."}]
        for f in dense:
            mr += [{"type": "text", "text": f"Dense original frame at {f['timestamp']} seconds"},
                   {"type": "image_url", "image_url": {"url": data_url(Path(f["path"]), "image/png")}}]
        m = client.call(f"motion_review_{wi}", mr, max_tokens=4500)
        if (not isinstance(m.get("observations"), list)
                or m.get("contact") not in ("observed", "not_observed", "unclear")
                or m.get("causal_link") not in ("observed", "unconfirmed")):
            raise ValueError("Invalid PRO motion review")
        if m["causal_link"] == "observed" and not m.get("supported_causal_action"):
            raise ValueError("Observed causal link lacks an identified action")
        m["focus_window"] = [fs, fe]
        motions.append(m)
    wjson(prodir / "motion_review.json", motions)
    motion = motions[0]
    confirmed_all = all(m["causal_link"] == "observed" for m in motions)
    sparse = select_frames(src, initial)
    er = [{"type": "text", "text": "Independently inspect these sparse ORIGINAL frames across the whole video. Report only DIRECTLY VISIBLE facial expression/gaze changes, per person and time interval. If face is too small, turned away or obscured, use null for visible_expression and inferred_emotion. Do not infer emotion from the story or motion alone. Do not make claims about audio, dialogue, contact or causality. Return JSON only: {\"person_expressions\":[{\"person_description\":\"\",\"start\":0,\"end\":1,\"visible_expression\":null,\"inferred_emotion\":null,\"evidence_timestamps\":[]}],\"uncertainties\":[]}."}]
    for f in sparse:
        er += [{"type": "text", "text": f"Sparse original frame at {f['timestamp']} seconds"},
               {"type": "image_url", "image_url": {"url": data_url(Path(f['path']), "image/png")}}]
    expr = client.call("expression_review", er, max_tokens=4500)
    if not isinstance(expr.get("person_expressions"), list):
        raise ValueError("Invalid PRO expression review")
    wjson(prodir / "expression_review.json", expr)
    analysis = client.call("reconcile", PRO_ANALYSIS + "\nReconcile the whole-video draft with INDEPENDENT reviews. Use frames to correct conflicts, but preserve unaffected chronology. Keep stable character IDs, shot IDs, full beat coverage (beat count must only grow, never merge), and per-character expression fields. MOTION reviews take precedence for action causality; EXPRESSION review only supports facial expressions. If any motion review causal_link is unconfirmed, remove every specific causal action or takedown from story, subject, beats and negatives for its window. No observed contact is not proof that contact never happened between frames. Never assert a cause from mere temporal proximity. Optional user text is unverified and never overrides video. Return the same full JSON schema.\n" + json.dumps({"draft": initial, "motion_reviews": motions, "expression_review": expr, "focus_windows": fs_list, "optional_user_text": ""}, ensure_ascii=False), compiler=True, max_tokens=10000)
    validate_pro(analysis, src["duration_seconds"])
    for (fs, fe), m in zip(fs_list, motions):
        try:
            clean_analysis(analysis, fs, fe, m["causal_link"] == "observed", expr)
        except ValueError:
            neutralize(client, analysis, m, fs, fe)
            clean_analysis(analysis, fs, fe, m["causal_link"] == "observed", expr)
    validate_pro(analysis, src["duration_seconds"])
    story = client.call("story", "Summarize the FULL chronological story or visual progression from this FINAL structured timeline, not the earlier draft. Include opening, middle and ending without inventing motives, contact, causes, facial expressions or emotions absent from the beats. If an event's causality is unconfirmed, describe only visible states. Return JSON only: {\"summary\":string,\"pacing\":string|null}.\n" + json.dumps({"shots": analysis["shots"], "global": analysis["global"], "causal_links": [m["causal_link"] for m in motions]}, ensure_ascii=False), compiler=True, max_tokens=1500)
    if not isinstance(story.get("summary"), str) or not story["summary"].strip() or "pacing" not in story:
        raise ValueError("Invalid final story")
    analysis["story"] = story
    for (fs, fe), m in zip(fs_list, motions):
        try:
            clean_analysis(analysis, fs, fe, m["causal_link"] == "observed", expr)
        except ValueError:
            neutralize(client, analysis, m, fs, fe)
            clean_analysis(analysis, fs, fe, m["causal_link"] == "observed", expr)
    if any(m["causal_link"] == "unconfirmed" for m in motions):
        bnd = "The focused action's exact causal mechanism is not directly confirmed by the reviewed frames."
        if bnd not in analysis["uncertainties"]:
            analysis["uncertainties"].append(bnd)
    wjson(prodir / "analysis.json", analysis)
    texts = collect_texts(analysis)
    tr = client.call("translate", "Translate the following English values into natural Chinese. Preserve their exact meaning, uncertainty and level of evidence. Do not add facts. Return JSON only with shape {\"translations\":{...}} and EXACTLY the same keys, each mapped to a nonempty Chinese string.\n" + json.dumps(texts, ensure_ascii=False), compiler=True, max_tokens=10000).get("translations", {})
    missing = {k: v for k, v in texts.items() if k not in tr}
    if missing:
        sup = client.call("translate_missing", "Translate ONLY these missing keys into natural Chinese, preserving meaning and uncertainty. Return JSON only: {\"translations\":{...}}.\n" + json.dumps(missing, ensure_ascii=False), compiler=True, max_tokens=2000)
        if isinstance(sup.get("translations"), dict):
            tr.update(sup["translations"])
    if set(tr) != set(texts) or any(not isinstance(x, str) or not x.strip() for x in tr.values()):
        raise ValueError("Incomplete bilingual translation map")
    wjson(prodir / "translations.json", tr)
    zh_pos, zh_neg = render_pro(analysis, src, tr, "zh")
    en_pos, en_neg = render_pro(analysis, src, tr, "en")
    prompts = {"zh_positive": zh_pos, "zh_negative": zh_neg, "en_positive": en_pos, "en_negative": en_neg}
    wjson(prodir / "prompts.json", prompts)
    for lang in ("zh", "en"):
        L = LABELS[lang]
        (prodir / f"prompt_{lang}.txt").write_text(
            f"{L['positive']}\n\n{prompts[f'{lang}_positive']}\n\n{L['negative']}\n\n{prompts[f'{lang}_negative']}\n", encoding="utf-8")
    (out / "prompt_zh.md").write_text(render_markdown(prompts, "zh"), encoding="utf-8")
    (out / "prompt_en.md").write_text(render_markdown(prompts, "en"), encoding="utf-8")
    sel = select_frames(src, analysis)
    (out / "evidence_gallery.md").write_text("\n\n".join(
        f"{next((s for s in analysis['shots'] if s['start'] <= f['timestamp'] <= s['end']), analysis['shots'][-1])['id']} · {f['timestamp']}s\n\n![{f['id']}]({f['path']})" for f in sel) + "\n", encoding="utf-8")
    rows = ["| Shot | Time | Camera | Beats |", "|---|---|---|---|"]
    for s in analysis["shots"]:
        beats = "; ".join(f"{bb['start']}–{bb['end']}: " + ", ".join(
            f"{pp['character_id']} {pp.get('action') or ''}" for pp in bb["participants"]) for bb in s["beats"])
        rows.append(f"| {s['id']} | {s['start']}–{s['end']} | {s.get('camera_motion') or 'unknown'} | {beats} |")
    (out / "shots.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    wjson(out / "structured.json", {"schema_version": "pro-1",
        "source": {k: v for k, v in src.items() if k != "visual_evidence"},
        "story": analysis["story"], "global": analysis["global"], "shots": analysis["shots"],
        "negative_constraints": analysis["negative_constraints"], "uncertainties": analysis["uncertainties"],
        "visual_evidence": sel})
    wjson(out / "manifest.json", {"scheme": "pro-full", "model": "google/gemini-3.8-flash",
        "shot_count": len(analysis["shots"]), "source_sha256": src["sha256"], "calls": client.calls})
    print(f"OK -> {out.resolve()} shots={len(analysis['shots'])}")

if __name__ == "__main__":
    main()
