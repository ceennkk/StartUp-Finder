"""Pitch v2 (~2:30): first half animated explainer, second half the real website.

kind "html": rendered from scenes.html (deterministic animation).
kind "site": captured from the running frontend (http://localhost:3000) with a scripted cursor.
"""

SCENES = [
    # ---- Part 1: animated explainer ----
    {"id": "hook", "hold": 1.5, "kind": "html", "voice": "[calm, confident] Tomorrow's founders are already visible today. You just have to know where to look."},
    {"id": "problem", "hold": 1, "kind": "html", "voice": "Spin-outs. Grant lists. Research projects. New code. Hundreds of sources, every single day. No team in the world can read it all."},
    {"id": "intro", "hold": 2, "kind": "html", "voice": "[warm] That's why we built Startup Finder."},
    {"id": "collect", "hold": 1, "kind": "html", "voice": "Startup Finder reads public sources around the clock and keeps every record together with its origin."},
    {"id": "select", "hold": 1, "kind": "html", "voice": "A decision model checks every record: does it name a real, new venture? Everything else is filtered out."},
    {"id": "connect", "hold": 1, "kind": "html", "voice": "A language model links people, ventures and funding programmes in a temporal knowledge graph. Every fact keeps its source and its lifetime."},
    {"id": "rank", "hold": 1.5, "kind": "html", "voice": "Then comes the assessment: founding intent, technical substance, customer problem, demand. The model judges, code does the maths. No evidence, no score."},
    {"id": "bridge", "hold": 1, "kind": "html", "voice": "[measured] Here's what that looks like in practice."},
    # ---- Part 2: the real website ----
    {"id": "site_home", "hold": 5, "kind": "site", "voice": "The home page shows, live, what is happening in your sources right now, and the strongest candidate at the moment, with evidence straight from the source."},
    {"id": "site_discover", "hold": 5, "kind": "site", "voice": "In Discover, every candidate is a bubble. The bigger the bubble, the stronger the evidence. One click opens the profile."},
    {"id": "site_profile", "hold": 5, "kind": "site", "voice": "The profile has everything you need: description, team, connected organisations and, for every criterion, the reasoning. Always with a source."},
    {"id": "site_shortlist", "hold": 2, "kind": "site", "voice": "Promising teams land on the shortlist with a single click."},
    {"id": "site_how", "hold": 5, "kind": "site", "voice": "And if you want to know how it all works, the whole pipeline is explained transparently, right down to the knowledge graph."},
    # ---- Outro ----
    {"id": "end", "hold": 2.5, "kind": "html", "voice": "[warm, confident] Startup Finder. Find the founders before everyone else."},
]

VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George (premade)
TTS_MODEL = "eleven_v4"
LANGUAGE = "en"

MUSIC_PROMPT = (
    "Premium minimal tech product film score, like an Apple keynote reveal. 100 BPM, warm analog synth pulses, "
    "soft sub bass, airy pads, delicate piano motif, clean modern percussion entering after the first quarter, "
    "uplifting and confident but understated, no vocals. Gentle build in the first half, steady confident groove "
    "in the second half, soft resolved ending."
)
SFX_WHOOSH = "Very soft airy whoosh transition, subtle, clean, short"
SFX_CLICK = "Soft subtle UI mouse click, clean, minimal"

PAD_BEFORE = 0.45
PAD_AFTER = 0.75
SITE_URL = "http://localhost:3000"
