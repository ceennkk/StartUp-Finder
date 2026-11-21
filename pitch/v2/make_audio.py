"""Generate voiceover, music and transition SFX with ElevenLabs into pitch/out/.

Writes out/timeline.json (scene start/duration) used by render_video.py.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

from script import (
    LANGUAGE,
    MUSIC_PROMPT,
    PAD_AFTER,
    PAD_BEFORE,
    SCENES,
    SFX_CLICK,
    SFX_WHOOSH,
    TTS_MODEL,
    VOICE_ID,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

load_dotenv(ROOT / ".env")  # SDK reads ELEVENLABS_API_KEY


def write_stream(chunks, path: Path) -> None:
    tmp = path.with_suffix(".part")
    with open(tmp, "wb") as f:
        for chunk in chunks:
            f.write(chunk)
    tmp.rename(path)  # no empty file left behind if the request fails


def duration(path: Path) -> float:
    err = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not m:
        raise RuntimeError(f"Could not read duration of {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])

    timeline, t = [], 0.0
    for i, s in enumerate(SCENES):
        path = OUT / f"voice_{i:02d}_{s['id']}.mp3"
        if not path.exists():
            print(f"TTS {s['id']} …")
            write_stream(
                client.text_to_speech.convert(
                    voice_id=VOICE_ID,
                    model_id=TTS_MODEL,
                    language_code=LANGUAGE,
                    text=s["voice"],
                    voice_settings=VoiceSettings(stability=0.6, similarity_boost=0.75),
                    output_format="mp3_44100_128",
                ),
                path,
            )
        d = PAD_BEFORE + duration(path) + PAD_AFTER + s.get("hold", 0)
        timeline.append({"id": s["id"], "kind": s["kind"], "start": round(t, 3), "duration": round(d, 3), "voice": path.name})
        t += d
    total = t  # short tail on the end card

    music = OUT / "music.mp3"
    if not music.exists():
        print(f"Music ({total:.1f}s) …")
        write_stream(
            client.music.compose(
                prompt=MUSIC_PROMPT,
                music_length_ms=int(total * 1000) + 2000,
                model_id="music_v2_5",
                force_instrumental=True,
            ),
            music,
        )

    for name, prompt, secs in (("whoosh.mp3", SFX_WHOOSH, 1.2), ("click.mp3", SFX_CLICK, 0.5)):
        sfx = OUT / name
        if not sfx.exists():
            print(f"SFX {name} …")
            write_stream(client.text_to_sound_effects.convert(text=prompt, model_id="eleven_text_to_sound_v3", duration_seconds=secs), sfx)

    (OUT / "timeline.json").write_text(json.dumps({"total": round(total, 3), "scenes": timeline}, indent=2))
    print(f"Done: {len(timeline)} scenes, {total:.1f}s → {OUT}")


if __name__ == "__main__":
    main()
