"""Render scenes.html frame by frame (Playwright) and mix it with the ElevenLabs audio into out/pitch.mp4.

Run make_audio.py first; it writes out/timeline.json.
"""

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 25
W, H = 1920, 1080


def render_frames(timeline: dict, silent: Path) -> None:
    n = int(timeline["total"] * FPS)
    enc = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", str(silent)],
        stdin=subprocess.PIPE,
    )
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")  # local Google Chrome
        except Exception:
            browser = p.chromium.launch()  # needs `playwright install chromium`
        page = browser.new_page(viewport={"width": W, "height": H})
        page.goto((HERE / "scenes.html").as_uri())
        page.evaluate("document.fonts.ready")
        page.evaluate("(tl) => setup(tl)", timeline)
        for i in range(n):
            page.evaluate(f"render({i / FPS})")
            enc.stdin.write(page.screenshot(type="png"))
            if i % (FPS * 5) == 0:
                print(f"  frame {i}/{n}")
        browser.close()
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")


def mix(timeline: dict, silent: Path, final: Path) -> None:
    inputs, filters, labels = ["-i", str(silent)], [], []
    idx = 1
    for s in timeline["scenes"]:
        inputs += ["-i", str(OUT / s["voice"])]
        ms = int((s["start"] + 0.5) * 1000)
        filters.append(f"[{idx}:a]adelay={ms}|{ms},volume=1.0[v{idx}]")
        labels.append(f"[v{idx}]")
        idx += 1
    for k, s in enumerate(timeline["scenes"][1:]):  # whoosh on each scene change
        inputs += ["-i", str(OUT / "whoosh.mp3")]
        ms = max(int((s["start"] - 0.35) * 1000), 0)
        filters.append(f"[{idx}:a]adelay={ms}|{ms},volume=0.35[s{k}]")
        labels.append(f"[s{k}]")
        idx += 1
    total = timeline["total"]
    inputs += ["-i", str(OUT / "music.mp3")]
    filters.append(f"[{idx}:a]atrim=0:{total},volume=0.22,afade=t=in:d=1.5,afade=t=out:st={total - 2.5}:d=2.5[m]")
    labels.append("[m]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)],
        check=True,
    )


def main() -> None:
    timeline = json.loads((OUT / "timeline.json").read_text())
    silent, final = OUT / "video_silent.mp4", OUT / "pitch.mp4"
    print(f"Rendering {timeline['total']:.1f}s at {FPS} fps …")
    render_frames(timeline, silent)
    print("Mixing audio …")
    mix(timeline, silent, final)
    print(f"Done → {final}")


if __name__ == "__main__":
    main()
