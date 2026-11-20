# Pitch-Video (ElevenLabs + HTGF-Frontend-Stil)

- `script.py` – Sprechertext pro Szene, Stimme, Musik- und SFX-Prompt
- `make_audio.py` – erzeugt Sprecherspur, Musik und Übergangs-Whoosh mit ElevenLabs (`out/`)
- `scenes.html` – Szenen im Stil des Frontends (ES Face, Avant Garde, Pills, Mastergradient); im Browser öffnen und `setup`/`render(t)` aufrufen
- `render_video.py` – rendert die Szenen Bild für Bild und mischt den Ton zu `out/pitch.mp4`

Der Schlüssel kommt aus `../.env` (`ELEVENLABS_API_KEY`), nie aus dem Code.

```bash
cd pitch
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python make_audio.py
.venv/bin/python render_video.py
```

Bereits erzeugte Audiodateien werden wiederverwendet; zum Neu-Erzeugen die Datei in `out/` löschen.
Alle Firmen und Personen im Video sind Demodaten und im Bild als „synthetisch“ gekennzeichnet.
