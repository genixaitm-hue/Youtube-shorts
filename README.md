# YouTube Shorts — Geopolitical Animated Explainers

**Goal of this repo:** produce fully-automated, research-verified, map-accurate YouTube Shorts that explain geopolitical events. Every short is generated from code — geospatial data, computed camera moves, typography and animation are all rendered programmatically, so the pipeline is reproducible: no third-party footage, no hand-drawn borders, every fact sourced and dated.

This first production is:

## 🎬 "Falklands War: 74 Days"

A 54-second vertical Short (1080×1920, 30 fps, H.264 High) on the 1982 Falklands War between the United Kingdom and Argentina (2 April – 14 June 1982), plus the status of the dispute today. Historical events (1982), the 2013 referendum and the 2026 state of the dispute are kept separate and dated. The final video has **no burned-in captions** (captions ship separately as `.srt` for YouTube to overlay) and **no audio track** (narration/music added separately).

---

## 📦 Repository assets

### Finished media
| Asset | Description |
|---|---|
| `final_video.mp4` | The rendered Short — 1080×1920, 30 fps, H.264 (High), 54 s. No audio, no burned-in captions (clean version). |
| `final_video_captioned.mp4` | **Publish-ready version** — same 54 s video with burned-in captions and the ElevenLabs narration muxed in (AAC 192 kbps, −16 LUFS). |
| `captioned_video.mp4` | Intermediate: the video with burned-in captions, no audio. |
| `narration.wav` | The narration-only track (44.1 kHz stereo, −16.2 LUFS) — each segment time-stretched to its exact video window so it stays in sync. |
| `thumbnail.png` | 1080×1920 thumbnail generated from the hook frame: "THE FALKLANDS / WAR / 74 DAYS · UK vs ARGENTINA". |

### Content / source-of-truth
| Asset | Description |
|---|---|
| `content.py` | **Single source of truth** for narration segments, captions and HUD date cards (timed in seconds). `render_video.py`, `make_text_assets.py` and the thumbnail script all read from here, so nothing can drift. |
| `voiceover_script.json` | Timed narration segments (9 segments, each with `start`/`end`, `text`, `emotion`, `delivery`, `pause_after`) ready for a text-to-speech tool. |
| `narration.txt` | Plain-text narration for recording or VO review. |
| `captions.srt` | The same caption text as an SRT file — upload to YouTube for accessibility. |

### Documentation
| Asset | Description |
|---|---|
| `research_report.md` | Verified facts: timeline, casualty figures, 2013 referendum, 2026 dispute state — with explicit disclosure of which on-screen graphics are illustrative. |
| `sources.md` | Full source list: Britannica, Falkland Islands National Archives, The Gazette (UK), Royal Navy museums, Reuters/AP/Al Jazeera, plus data-asset licences (Natural Earth, flag-icons, Poppins OFL). |
| `storyboard.md` | Scene-by-scene plan (times, visuals, on-screen text, narration) with safe-area notes for the Shorts UI. |
| `youtube_metadata.md` | Ready-to-paste YouTube title, description, hashtags and pinned comment. |

### Production pipeline (Python 3)
| Asset | Description |
|---|---|
| `render_video.py` | The renderer. Loads Natural Earth polygons via **GeoPandas/Shapely**, projects them in Web-Mercator, computes geodesic distances with **PyProj** (WGS84), renders anti-aliased vector maps and camera moves with **OpenCV**, typography/sprites with **Pillow**, flags with **CairoSVG**, then encodes with **FFmpeg/libx264**. Camera keyframes live in the `KEYS` list. |
| `make_text_assets.py` | Regenerates `voiceover_script.json`, `narration.txt` and `captions.srt` from `content.py`. |
| `make_thumbnail.py` | Renders the hook frame (`render(4.4)`) and overlays the headline text to produce `thumbnail.png`. |
| `build_audio.py` | Generates the narration with ElevenLabs, trims silence, time-stretches every segment to its exact video window (`end − start − pause_after`), lays the clips on the 54 s timeline, normalises loudness, burns captions into `final_video.mp4` and muxes the audio. Requires `ELEVENLABS_API_KEY` (voice via `ELEVENLABS_VOICE`, default: the account's instant voice clone). |

### `project_assets/` (bundled data)
| Folder | Files | Purpose / licence |
|---|---|---|
| `maps/` | `ne_10m_admin_0_countries.geojson` | Natural Earth 10m admin-0 country polygons — the only border data used; nothing hand-drawn. **Public domain.** |
| `flags/` | `gb.svg`, `ar.svg`, `fk.svg`, `flag-icons-LICENSE` | Flag sprites for the UK / Argentina / Falklands. From [flag-icons](https://github.com/lipis/flag-icons). **MIT licence.** |
| `fonts/` | `Poppins-Bold.ttf`, `Poppins-Medium.ttf`, `Poppins-Regular.ttf` | Typography. **SIL Open Font License.** |
| `graphics/` | `frame_*.png` (10 stills) | QC frame stills from across the timeline, used for visual review and the thumbnail. |

---

## 🔁 Regenerate everything

```bash
pip install geopandas shapely pyproj pyogrio cairosvg opencv-python pillow numpy

python3 make_text_assets.py           # → voiceover_script.json, narration.txt, captions.srt
python3 render_video.py               # → final_video.mp4 (~10 min on 1 CPU)
python3 render_video.py --test 5 20   # preview single frames to /tmp/test
python3 make_thumbnail.py             # → thumbnail.png
```

### Audio + captions (ElevenLabs)

```bash
export ELEVENLABS_API_KEY=sk_...        # required
export ELEVENLABS_VOICE=pNInz6obpgDQGcFmaJgB   # optional; your instant voice clone
python3 build_audio.py                   # → narration.wav, captioned_video.mp4, final_video_captioned.mp4
```

**Why the audio used to drift:** each ElevenLabs clip is naturally ~20–45 % longer than its caption/video window, so simply concatenating the clips made the voice fall behind the map. `build_audio.py` fixes this by measuring every clip, trimming silence, and time-stretching (`atempo`) each one to fit its exact window (`end − start − pause_after`), then placing it at its `start` on the 54 s timeline. Speech onsets now land exactly on the segment boundaries (0, 5.4, 12.4, 17.6, 24, 30, 35, 41.5, 46 s).

Edit narration, captions and date cards in `content.py`; camera moves are the `KEYS` list in `render_video.py`.

## 🗣 Using the voiceover JSON
Each segment has `start`/`end` (seconds in the video), `text`, `emotion`, `delivery` and `pause_after`. Generate one audio clip per segment (speed 1.0), place each at its `start`, and trim/stretch slightly if a clip exceeds its window. Segments are timed to caption and map events. Add music separately, under the voice.

## ⚠️ Honest limitations
- The invasion arrow, task-force route and San Carlos → Stanley arrow are **illustrative** (direction only); the route is labelled on screen.
- Casualty counts differ slightly across sources (an on-screen note is included).
- The 2026 dispute is moving quickly; the video states only the stable core. Re-check `research_report.md` before publishing.
