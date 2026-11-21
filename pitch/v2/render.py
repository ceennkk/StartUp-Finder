"""Render pitch v2: animated scenes (scenes.html) + scripted capture of the live website, mixed with ElevenLabs audio.

Prereqs: run make_audio.py first; the frontend must be running on SITE_URL with the live backend.
Output: out/pitch_v2.mp4 (1920x1080, 25 fps).
"""

import json
import math
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

from script import SITE_URL

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 25
W, H = 1920, 1080
SITE_VIEW = {"width": 1600, "height": 900}  # rendered at 1.2x → 1920x1080


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class Encoder:
    def __init__(self, path: Path):
        self.proc = subprocess.Popen(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium", str(path)],
            stdin=subprocess.PIPE,
        )

    def add(self, png: bytes) -> None:
        self.proc.stdin.write(png)

    def close(self) -> None:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg encode failed")


# ---------------- website capture helpers ----------------
CAPTURE_CSS = """
.fa-chat, nextjs-portal, [data-nextjs-toast], #__next-build-watcher { display: none !important; }
.hm-ticker__track { animation: none !important; }
html { scroll-behavior: auto !important; }
#pitch-cursor { position: fixed; z-index: 2147483647; left: 0; top: 0; width: 26px; height: 26px; pointer-events: none; transform: translate(-3px, -2px); }
#pitch-cursor svg { width: 26px; height: 26px; filter: drop-shadow(0 2px 4px rgba(0,0,0,.25)); }
#pitch-ring { position: fixed; z-index: 2147483646; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%; border: 2px solid #000; pointer-events: none; opacity: 0; }
"""
CURSOR_JS = """
() => {
  if (document.getElementById('pitch-cursor')) return;
  const s = document.createElement('style'); s.textContent = %s; document.head.appendChild(s);
  const c = document.createElement('div'); c.id = 'pitch-cursor';
  c.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.5 14.8 L11.6 21.5 L14.2 20.3 L11.2 13.8 L17.5 13.8 Z" fill="#000" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  const r = document.createElement('div'); r.id = 'pitch-ring'; document.body.appendChild(r);
}
""" % json.dumps(CAPTURE_CSS)


class Site:
    def __init__(self, page: Page):
        self.page = page
        self.cursor = (800.0, 450.0)

    def prep(self) -> None:
        self.page.evaluate(CURSOR_JS)

    def goto(self, route: str, wait_for: str, settle: float = 1.5) -> None:
        self.page.evaluate(f"location.hash = '{route}'")
        self.page.wait_for_selector(wait_for, timeout=60000)
        self.page.wait_for_timeout(int(settle * 1000))
        self.prep()

    def center(self, selector: str) -> tuple[float, float]:
        box = self.page.locator(selector).first.bounding_box()
        if not box:
            return self.cursor
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def frame(self, cursor: tuple[float, float], ring: float = 0.0, ticker_t: float | None = None, js: str | None = None) -> bytes:
        x, y = cursor
        self.cursor = cursor
        self.page.mouse.move(x, y)
        extra = js or ""
        ticker = f"const tr=document.querySelector('.hm-ticker__track'); if(tr) tr.style.transform='translateX(-{ticker_t * 55:.1f}px)';" if ticker_t is not None else ""
        self.page.evaluate(
            f"() => {{ const c=document.getElementById('pitch-cursor'); if(c){{c.style.left='{x}px';c.style.top='{y}px';}}"
            f" const r=document.getElementById('pitch-ring'); if(r){{r.style.left='{x}px';r.style.top='{y}px';r.style.opacity='{max(0.0, 1 - ring):.2f}';r.style.transform='scale({0.6 + ring * 0.9:.2f})';}}"
            f" {ticker} {extra} }}"
        )
        return self.page.screenshot(type="png")


def lerp(a: tuple[float, float], b: tuple[float, float], q: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q


def capture_site(page: Page, enc: Encoder, seg: dict) -> None:
    site = Site(page)
    n = round(seg["duration"] * FPS)
    sid = seg["id"]
    print(f"  {sid}: {n} frames")

    if sid == "site_home":
        site.goto("#/home", ".hm-feature__score", settle=3)
        page.evaluate("window.scrollTo(0,0)")
        feat_top = page.evaluate("document.querySelector('.hm-feature').getBoundingClientRect().top + scrollY - 70")
        start, end_c = (1150.0, 760.0), (420.0, 790.0)
        for i in range(n):
            t = i / FPS
            q = ease((t - 3.0) / (seg["duration"] - 5.5))
            y = feat_top * q
            page.evaluate(f"window.scrollTo(0,{y:.1f})")
            enc.add(site.frame(lerp(start, end_c, ease((t - 2) / (seg["duration"] - 3))), ticker_t=t))

    elif sid == "site_discover":
        site.goto("#/entdecken", ".fa-landscape__bubble", settle=2)
        page.evaluate("window.scrollTo(0,0)")
        bubbles = page.locator(".fa-landscape__bubble")
        stops = [site.center(".fa-landscape__bubble >> nth=%d" % k) for k in (3, 1, 0)]
        start = (1250.0, 300.0)
        click_at = seg["duration"] - 1.6
        for i in range(n):
            t = i / FPS
            if t < 2.0:
                c = start
            elif t < 4.5:
                c = lerp(start, stops[0], ease((t - 2) / 2.5))
            elif t < 6.5:
                c = lerp(stops[0], stops[1], ease((t - 4.5) / 2.0))
            else:
                c = lerp(stops[1], stops[2], ease((t - 6.5) / max(click_at - 6.5, 0.5)))
            ring = (t - click_at) / 0.5 if click_at <= t < click_at + 0.5 else 1.0
            enc.add(site.frame(c, ring=ring))
        bubbles.first.click()

    elif sid == "site_profile":
        page.wait_for_selector(".fa-pmap__modal", timeout=60000)
        page.wait_for_function("() => !document.querySelector('.fa-pmap__modal')?.textContent?.match(/Loading|Lade/)", timeout=60000)
        page.wait_for_timeout(1500)
        site.prep()
        depth = page.evaluate("Math.min(document.querySelector('.fa-pmap__modal').scrollHeight - document.querySelector('.fa-pmap__modal').clientHeight, 2400)")
        c = (1180.0, 520.0)
        for i in range(n):
            t = i / FPS
            q = ease((t - 2.0) / (seg["duration"] - 3.5))
            enc.add(site.frame(c, js=f"document.querySelector('.fa-pmap__modal').scrollTop={depth * q:.1f};"))

    elif sid == "site_shortlist":
        page.keyboard.press("Escape")
        site.goto("#/shortlist", ".fa-shortlist__item, .fa-empty", settle=1.5)
        target = site.center(".fa-shortlist__item")
        start = (1100.0, 600.0)
        for i in range(n):
            t = i / FPS
            enc.add(site.frame(lerp(start, target, ease((t - 0.8) / 2.5))))

    elif sid == "site_how":
        site.goto("#/pipeline", ".hx-hero", settle=1.5)
        page.evaluate("window.scrollTo(0,0)")
        bottom = page.evaluate("document.querySelector('.hx-tech').getBoundingClientRect().top + scrollY + 900")
        c = (1480.0, 820.0)
        for i in range(n):
            t = i / FPS
            q = ease((t - 1.5) / (seg["duration"] - 2.5))
            page.evaluate(f"window.scrollTo(0,{bottom * q:.1f})")
            enc.add(site.frame(c))


def render_html(page: Page, enc: Encoder, timeline: dict, seg: dict) -> None:
    n = round(seg["duration"] * FPS)
    print(f"  {seg['id']}: {n} frames")
    for i in range(n):
        page.evaluate(f"render({seg['start'] + i / FPS})")
        enc.add(page.screenshot(type="png"))


def mix(timeline: dict, silent: Path, final: Path) -> None:
    inputs, filters, labels, idx = ["-i", str(silent)], [], [], 1
    for s in timeline["scenes"]:
        inputs += ["-i", str(OUT / s["voice"])]
        ms = int((s["start"] + 0.45) * 1000)
        filters.append(f"[{idx}:a]adelay={ms}|{ms}[v{idx}]"); labels.append(f"[v{idx}]"); idx += 1
    for k, s in enumerate(timeline["scenes"][1:]):
        inputs += ["-i", str(OUT / "whoosh.mp3")]
        ms = max(int((s["start"] - 0.35) * 1000), 0)
        filters.append(f"[{idx}:a]adelay={ms}|{ms},volume=0.3[s{k}]"); labels.append(f"[s{k}]"); idx += 1
    disc = next(s for s in timeline["scenes"] if s["id"] == "site_discover")
    click_ms = int((disc["start"] + disc["duration"] - 1.6) * 1000)
    inputs += ["-i", str(OUT / "click.mp3")]
    filters.append(f"[{idx}:a]adelay={click_ms}|{click_ms},volume=0.6[c0]"); labels.append("[c0]"); idx += 1
    total = timeline["total"]
    inputs += ["-i", str(OUT / "music.mp3")]
    filters.append(f"[{idx}:a]atrim=0:{total},volume=0.2,afade=t=in:d=1.5,afade=t=out:st={total - 3}:d=3[m]"); labels.append("[m]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)], check=True)


def main() -> None:
    timeline = json.loads((OUT / "timeline.json").read_text())
    silent, final = OUT / "video_silent.mp4", OUT / "pitch_v2.mp4"
    print(f"Rendering {timeline['total']:.1f}s …")
    enc = Encoder(silent)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()
        scenes_page = browser.new_page(viewport={"width": W, "height": H})
        scenes_page.goto((HERE / "scenes.html").as_uri())
        scenes_page.evaluate("document.fonts.ready")
        scenes_page.evaluate("(tl) => setup(tl)", timeline)

        site_ctx = browser.new_context(viewport=SITE_VIEW, device_scale_factor=W / SITE_VIEW["width"])
        site_page = site_ctx.new_page()
        site_page.add_init_script("try { localStorage.setItem('startup-finder-language', 'en') } catch (e) {}")
        site_page.goto(SITE_URL + "/#/home")
        site_page.wait_for_selector(".fa-bar", timeout=60000)

        for seg in timeline["scenes"]:
            if seg["kind"] == "html":
                render_html(scenes_page, enc, timeline, seg)
            else:
                capture_site(site_page, enc, seg)
        browser.close()
    enc.close()
    print("Mixing audio …")
    mix(timeline, silent, final)
    print(f"Done → {final}")


if __name__ == "__main__":
    main()
