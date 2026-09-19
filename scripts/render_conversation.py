"""Render a recorded conversation (scripts/conversations.py --record) at 1x into docs/demo.mp4 and docs/demo.gif.

The browser area is the original screencast. The side panel only restates what the report recorded:
each request, the action executing at that moment, and whether the request's independent check passed.
"""

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("recording", type=Path, help="Folder passed to conversations.py --record")
parser.add_argument("--name", default="youtube", help="Conversation to render")
args = parser.parse_args()
report = json.loads((args.recording / "report.json").read_text(encoding="utf-8"))
conversation = next(c for c in report["conversations"] if c["name"] == args.name)
requests = conversation["requests"]
assert all(r["passed"] for r in requests) and not conversation["recording_errors"], "Render verified runs only"
screencast = args.recording / args.name / "screencast"
shots = sorted((int(p.stem), p) for p in screencast.glob("*.jpg"))
metadata = json.loads((screencast / "metadata.json").read_text(encoding="utf-8"))
end_ms = round((requests[-1]["started_s"] + requests[-1]["seconds"]) * 1000)
out = args.recording / args.name / "video-frames"
out.mkdir(parents=True, exist_ok=False)

FONTS = {
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "mono": ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc"],
}


def font(size, kind="regular"):
    for path in FONTS[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def wrap(draw, text, face, width, lines=3):
    words, rows = text.split(), [""]
    for word in words:
        candidate = f"{rows[-1]} {word}".strip()
        if draw.textlength(candidate, font=face) <= width:
            rows[-1] = candidate
        else:
            rows.append(word)
    if len(rows) > lines:
        rows = rows[:lines]
        rows[-1] = rows[-1].rstrip(".,") + "…"
    return rows


def short(text, face, width, draw):
    text = " ".join(text.split())
    while draw.textlength(text, font=face) > width and len(text) > 4:
        text = text[:-2].rstrip() + "…" if not text.endswith("…") else text[:-2] + "…"
    return text


bg, ink, muted, green, soft, accent, red = "#f3f4ec", "#172a20", "#6a766c", "#2a743f", "#dfebd9", "#ea7345", "#b3412c"
cache = {}


def screenshot(t):
    ms, path = next(((ms, p) for ms, p in reversed(shots) if ms <= t), shots[0])
    if path not in cache:
        cache.clear()
        image = Image.open(path).convert("RGB")
        meta = metadata[path.stem]
        if image.size != (1120, 780):
            # Chrome captured its whole window surface; Jev's 1120x780 page is its top-left corner.
            scale = image.width / meta["deviceWidth"]
            top = meta["offsetTop"] * scale
            image = image.crop((0, round(top), round(1120 * scale), round(top + 780 * scale))).resize((1120, 780))
        image = image.crop((0, 0, 1120, 716))  # Keep the page's top (its search bar); trim the bottom.
        # Pixelate the signed-in account corner (avatar, notifications) in every frame.
        corner = image.crop((1010, 0, 1120, 60))
        image.paste(corner.resize((11, 6)).resize(corner.size, Image.NEAREST), (1010, 0))
        cache[path] = image
    return cache[path]


frames = round((end_ms + 1500) * 30 / 1000)  # A 1.5 s hold on the final page.
for i in range(frames):
    t = min(end_ms, round(i * 1000 / 30))
    now = t / 1000
    canvas = Image.new("RGB", (1536, 1000), bg)
    d = ImageDraw.Draw(canvas)
    d.text((36, 22), "Jev Ultrafast", font=font(24, "bold"), fill=ink)
    d.text((196, 24), "·  Browser Use × TypeSafe", font=font(21), fill=muted)
    d.rounded_rectangle((1287, 24, 1499, 59), radius=17, fill=soft)
    d.text((1307, 31), "REAL WEB  ·  1× SPEED", font=font(15, "bold"), fill=green)
    d.text((36, 70), "Say it. It browses.", font=font(46, "bold"), fill=ink)
    d.text((38, 134), "Spoken requests, one after another, each continuing where the last one ended.",
           font=font(20), fill=muted)
    d.rounded_rectangle((35, 191, 1157, 943), radius=14, fill="#202124")
    for j, c in enumerate(["#de8278", "#d6bd6e", "#8dbd8a"]):
        d.ellipse((54 + j * 19, 205, 63 + j * 19, 214), fill=c)
    active = next((r for r in reversed(requests) if r["started_s"] <= now), requests[0])
    d.text((145, 199), short(active["url"].split("://")[-1], font(14, "mono"), 980, d), font=font(14, "mono"),
           fill="#d4d6d5")
    canvas.paste(screenshot(t), (36, 226))

    d.text((1192, 196), f"{now:05.2f}", font=font(46, "mono"), fill=ink)
    d.text((1194, 252), "SECONDS, ALL REQUESTS", font=font(13, "bold"), fill=muted)
    y = 292
    for r in requests:
        if r["started_s"] > now:
            break
        face = font(19, "bold")
        rows = wrap(d, f"“{r['request']}”", face, 272)
        height = 34 + 26 * len(rows) + 44
        d.rounded_rectangle((1189, y, 1499, y + height), radius=12, fill="#ffffff" if r is active else "#eceee5")
        d.text((1205, y + 10), "YOU SAID", font=font(12, "bold"), fill=accent)
        for k, row in enumerate(rows):
            d.text((1205, y + 30 + 26 * k), row, font=face, fill=ink)
        finished = now >= r["started_s"] + r["seconds"]
        line_y = y + 34 + 26 * len(rows) + 6
        if finished:
            ok = r["passed"]
            # Drawn, not typed: common UI fonts have no check-mark glyph.
            d.ellipse((1205, line_y + 2, 1225, line_y + 22), fill=green if ok else red)
            if ok:
                d.line([(1210, line_y + 12), (1214, line_y + 16), (1221, line_y + 8)], fill="white", width=2)
            else:
                d.line([(1210, line_y + 7), (1220, line_y + 17)], fill="white", width=2)
                d.line([(1220, line_y + 7), (1210, line_y + 17)], fill="white", width=2)
            d.text((1233, line_y), f"{'Done' if ok else r['status'].capitalize()} in {r['seconds']:.1f} s",
                   font=font(17, "bold"), fill=green if ok else red)
        else:
            done = [a for a, at in zip(r["actions"], r["action_times_s"]) if at <= now]
            label = f"→ {done[-1]}" if done else "Reading the page…"
            d.text((1205, line_y), short(label, font(16), 272, d), font=font(16), fill=muted)
        y += height + 12

    d.line((37, 960, 1498, 960), fill="#d3d9cc", width=2)
    d.line((37, 960, 37 + (1498 - 37) * t / end_ms, 960), fill=green, width=3)
    helper = report.get("text_model") or "the text helper"
    d.text((37, 970), f"Operation + element chosen by TypeSafe Jev · typed text by {helper}"
           " · original timing, loading included · requests are speech transcripts",
           font=font(14), fill=muted)
    canvas.save(out / f"{i:05d}.png")
canvas.save(args.recording / args.name / "final-frame.png")
ffmpeg = ["ffmpeg", "-y", "-loglevel", "error"]
subprocess.run([*ffmpeg, "-framerate", "30", "-i", str(out / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "20", "-movflags", "+faststart", str(ROOT / "docs/demo.mp4")], check=True)
subprocess.run([*ffmpeg, "-i", str(ROOT / "docs/demo.mp4"), "-vf",
                "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer",
                "-loop", "0", str(ROOT / "docs/demo.gif")], check=True)
print(f"Rendered {len(shots)} screencast frames over {end_ms} ms at 1x, plus a 1.5 s final hold.")
