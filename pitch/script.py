"""Pitch script: one entry per scene. `voice` is spoken (ElevenLabs), `scene` names the visual in scenes.html."""

SCENES = [
    {
        "scene": "hook",
        "voice": "[calm, confident] Die besten Gründerinnen und Gründer sind schon da. Lange bevor es jemand merkt.",
    },
    {
        "scene": "sources",
        "voice": "Sie stehen in Pressemitteilungen, in Förderlisten, in Uni-Spin-offs. Verstreut, unsortiert, leicht zu übersehen.",
    },
    {
        "scene": "signals",
        "voice": "Startup Finder liest diese Quellen laufend mit, erkennt frühe Gründungssignale und verdichtet sie zu Profilen. Jede Aussage mit Fundstelle.",
    },
    {
        "scene": "ai",
        "voice": "[measured] Die KI schlägt vor. Ihr entscheidet. Einschätzungen bleiben getrennt von den Quelldaten. Keine Black Box, keine Erfolgswahrscheinlichkeiten.",
    },
    {
        "scene": "workflow",
        "voice": "Entdecken, merken, recherchieren. Shortlist, Notizen und Netzwerk an einem Ort.",
    },
    {
        "scene": "end",
        "voice": "[warm] Startup Finder. Find the founders before everyone else.",
    },
]

VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George (premade, works on free plans)
TTS_MODEL = "eleven_v4"
LANGUAGE = "de"

MUSIC_PROMPT = (
    "Minimal calm corporate ambient, about 90 BPM, soft analog synth pads, gentle pulsing bass, "
    "sparse clean piano motif, optimistic, premium and understated, no drums fills, no vocals. "
    "Builds very gently and resolves softly at the end."
)
SFX_PROMPT = "Very soft airy whoosh transition, subtle, clean, short"

PAD_BEFORE = 0.5  # seconds of silence before each line
PAD_AFTER = 0.7   # seconds after each line
