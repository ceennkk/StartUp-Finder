"""Pitch v3 · Find the Founder (Fassung B, judging criteria) (~2:30): first half animated explainer, second half the real website.

kind "html": rendered from scenes.html (deterministic animation).
kind "site": captured from the running frontend (http://localhost:3000) with a scripted cursor.
"""

SCENES = [
    {"id": "hook", "hold": 0.3, "kind": "html", "voice": "[calm, confident] Tomorrow's founders are already visible today. You just have to know where to look."},
    {"id": "early", "hold": 0.3, "kind": "html", "voice": "Before there is a company, there are signals: an EXIST grant, an EU research project, a new repository, a university spin-out announcement. Find the Founder reads exactly there, long before a startup shows up in any database."},
    {"id": "creative", "hold": 0.3, "kind": "html", "voice": "And where nobody else is looking: Hugging Face, CORDIS, trade fair catalogues."},
    {"id": "decide", "hold": 0.3, "kind": "html", "voice": "Most AI tools push everything through one big language model. We don't. A specialised decision model decides first: relevant or not, with a confidence and a reason. Only then does the language model extract. That's more precise, cheaper and traceable."},
    {"id": "temporal", "hold": 0.3, "kind": "html", "voice": "Classic RAG finds passages and forgets them again. GraphRAG connects facts, but without time. Our temporal knowledge graph knows when something was true. When the world changes, the old fact is closed, not overwritten. So we see the moment a researcher becomes a founder."},
    {"id": "rank", "hold": 0.3, "kind": "html", "voice": "Every profile is assessed: founding intent, technical substance, customer problem, demand. The model judges, code does the maths. No evidence, no score."},
    {"id": "arch", "hold": 0.3, "kind": "html", "voice": "Built like infrastructure. Every component is its own building block: source adapters, job queue, decision model, language model, graph. New sources are added by configuration. The queue is designed for many workers in parallel. More load simply means more workers."},
    {"id": "bridge", "hold": 0.3, "kind": "html", "voice": "[confident] And it runs. Live."},
    {"id": "site_home", "hold": 1.5, "kind": "site", "voice": "Live from our sources, and the strongest candidate with evidence straight from the source."},
    {"id": "site_discover", "hold": 1.5, "kind": "site", "voice": "Every candidate as a bubble. The bigger it is, the stronger the evidence."},
    {"id": "site_profile", "hold": 2, "kind": "site", "voice": "Team, network and, for every criterion, the reasoning. These are leads we would call tomorrow."},
    {"id": "site_how", "hold": 1.5, "kind": "site", "voice": "And the whole pipeline is transparent."},
    {"id": "fin_types", "hold": 0.6, "kind": "html", "voice": "Find the Founder tells grants apart from equity. Because not every euro means an investor holds shares."},
    {"id": "fin_review", "hold": 0.6, "kind": "html", "voice": "An investment only counts as confirmed once there is evidence and a person has reviewed it. That keeps every statement traceable."},
    {"id": "fin_export", "hold": 0.8, "kind": "html", "voice": "In the current MVP, these financial details live in a separate export, not yet in the database that powers the website."},
    {"id": "pick_intro", "hold": 0.6, "kind": "html", "voice": "Our top pick right now: nodeline, a spin-out from the KIT founder ecosystem in Karlsruhe. Its AI turns business requirements into secure data pipelines for industry and small manufacturers."},
    {"id": "pick_why", "hold": 0.8, "kind": "html", "voice": "Two founders straight out of research. Backed so far by a public grant of almost eight hundred thousand euros, not by equity. First pilot customers, a team being built. Early, technical, and no confirmed investor yet: exactly the moment to talk."},
    {"id": "end", "hold": 1.5, "kind": "html", "voice": "[warm, confident] Find the Founder. Meet tomorrow\'s founders before everyone else."},
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
