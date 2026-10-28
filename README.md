# Vivi – local AI desktop companion

Everything runs on this PC. Nothing leaves it.

| Part | What | Where | Port |
|---|---|---|---|
| Brain + eyes | Ollama, `gemma-4-12b` (chat, tools, vision) | Ollama service | 11434 |
| Voice | Kokoro-FastAPI (CPU) | `D:\AI\External\Kokoro-FastAPI` | 8880 |
| Body | ViviPet showing Capri (corner of screen, lip sync) | `D:\AI\External\ViviPet` | 18765 |
| Mind | this project: memory, learning, screen watcher, actions | `D:\AI\Companion` | 18800 |
| Hands (complex tasks) | OpenClaw gateway | `~\.openclaw` | 18789 |

## Setup (once)

ViviPet and Kokoro-FastAPI are third-party projects, so they are not stored in this repo. The scripts expect them in `D:\AI\External\` (change the paths at the top of `start_companion.ps1` if yours differ).

1. **Ollama:** install it, then `ollama pull hf.co/unsloth/gemma-4-12b-it-GGUF:Q4_K_M`.
2. **Kokoro:** clone [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) to `D:\AI\External\Kokoro-FastAPI` and set up its `.venv` (see its README). No changes to it are needed.
3. **ViviPet (the body):** run `integrations\vivipet\apply_patch.ps1`. It clones [ViviPet](https://github.com/suntianc/ViviPet) to `D:\AI\External\ViviPet` if it isn't there, applies `vivipet-companion.patch` (sprite + chibi renderers, chat box, Kokoro TTS, hotkey, reaction fixes; made against ViviPet commit `ffa2b9f`), downloads Capri's sprites, builds it, and writes ViviPet's Kokoro TTS config.
4. **Companion:** `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`.
5. **OpenClaw (optional):** point its default model at an installed Ollama model, e.g. `ollama/hf.co/unsloth/gemma-4-12b-it-GGUF:Q4_K_M`. Use the `ollama/` prefix, or OpenClaw reads `hf.co` as the provider.

## Run

```
D:\AI\Companion\start_companion.bat            # everything, in the background
D:\AI\Companion\start_companion.bat -Console   # brain in a console you can type into
D:\AI\Companion\start_companion.bat -NoScreen  # without screen watching
```

Talk to it by **double-clicking the pet** or pressing **Ctrl+Shift+Space**. Esc closes the box.
👍 / 👎 in the chat box tells it whether you liked its last unprompted remark. Clicking the pet's head, face or hands gets a reaction.

## The character

The default body is **Capri**, a full-size sprite character from [capri-desktop](https://github.com/lachydotmcg/capri-desktop) by Lachy. ViviPet plays her sprite sheets with `SpriteRenderer.ts` (added by the patch). Her art is **not** in this repo: `integrations/capri/fetch_capri_assets.ps1` downloads it from capri-desktop at a pinned commit, together with its license.

> Capri's art is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).
> Required Notice: Copyright 2026 Lachy (https://github.com/lachydotmcg)
> Personal / noncommercial use only. Anyone who gets a copy of the art must also get the license and this notice.

How the companion's states map to her animations:

| Companion state | Capri animation |
|---|---|
| idle / speaking | idle loop with blinks; mouth overlay lip-synced to Kokoro |
| happy, shy, head-pat | grin (+ sparkles / hearts) |
| excited, success, love | dance (+ sparkles / hearts) |
| surprised, error, angry | glitch (+ `!`, sweat drop, anger mark) |
| thinking, confused, working | idle with a lean + thought bubble, `?` or gear |
| sad | lean + tear |
| dragged | dangle |
| away 10 min → back | sleep loop with zzz → glitchy wake-up |
| app start | glitch-in entrance |

She turns to face your cursor. Emotions come from the conversation: the LLM tags each sentence (`[excited] Yes! [worried] But it's 3am...`), and the animation changes in time with the speech. Tools have their own poses while they run.

**Other bodies:** the tray menu's Switch Model also has **Vivi (Chibi)**, an original chibi drawn entirely in code (`ChibiRenderer.ts`), and ViviPet's Live2D models (Vivian/Jian). Change size from the tray as well.

## What it can do

- **Chat** with a persona (`config.yaml → companion.persona`), short spoken replies with emotions (her animation changes).
- **See the screen**: every ~20 s it checks the active window (cheap, no AI). When you switch to something new it *may* take a screenshot and make a short remark. Ask "what do you think of this?" and it looks right away. Screenshots stay in memory only and are never saved. Windows matching `privacy_blocklist` (password managers, banking, incognito) are never captured.
- **PC actions**: open websites, web search, YouTube (search or play the top result), launch any Start-menu app by name, media and volume keys.
- **OpenClaw**: complex multi-step tasks ("find the biggest files in Downloads", "fill in this form") go to the OpenClaw agent in the background, and Vivi tells you when it's done.
- **IoT**: add devices under `iot.devices` in `config.yaml` (Home Assistant entities or plain HTTP webhooks such as Shelly/Tasmota/ESPHome), then say "turn on the desk lamp".

## How it learns (save system)

All of it is in `data/memory.db` (SQLite). Back up that one file to keep your companion's memory.

| Table | Learned from | Used for |
|---|---|---|
| `facts` | `remember` tool calls + a background pass after each message that pulls out facts (name, job, likes, routines...). Each fact has a confidence that rises when it's repeated, and a new value replaces an old one. | Injected into every prompt; full-text recall of relevant facts |
| `episodes` | After 15 min of silence the conversation is summarized | "Last time we talked about..." |
| `app_usage` | Active-window time, per hour of day | Knowing your habits ("usually Blender at this hour") |
| `aliases` | Apps it found once are cached, and `learn_shortcut` ("'my music' means this playlist") | Faster, personal commands |
| `prefs` | **Adaptation**: `chattiness` goes up when you answer its remarks, down when you ignore them or press 👎, and you can say "talk less" / "stop watching my screen" | How often it speaks unprompted |
| `feedback` | Every like/dislike/ignored/touch event | Audit trail for tuning |

To see what it knows: `http://127.0.0.1:18800/memory`. Say "forget that I ..." to delete facts.

## Files

```
main.py               entry point
config.yaml           models, persona, voice, screen/privacy, OpenClaw, IoT
companion/brain.py    conversation loop, tool use, learning, adaptation, screen reactions
companion/memory.py   SQLite save system
companion/actions.py  tools (web, YouTube, apps, media, OpenClaw, IoT, memory)
companion/screen.py   active window, idle time, screenshots
companion/llm.py      Ollama client
companion/pet.py      ViviPet adapter client
companion/server.py   HTTP API (/chat, /react, /feedback, /memory)
integrations/vivipet/ patch + apply script + TTS config for the ViviPet body
integrations/capri/   downloads Capri's sprite sheets + license (not stored here)
run_kokoro_logged.bat starts Kokoro with output logged to data/kokoro.log
```
