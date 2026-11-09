#!/usr/bin/env python3
"""Build the narrated, captioned Short.

1. Generate every narration segment with ElevenLabs (voice from ELEVENLABS_VOICE,
   key from ELEVENLABS_API_KEY).
2. Trim leading/trailing silence, then time-stretch each clip so it fits its
   exact video window (end - start - pause_after). This is what keeps the voice
   in sync with the map/caption events instead of drifting behind them.
3. Lay the clips on the 54 s timeline, normalise loudness for YouTube.
4. Burn captions into final_video.mp4 and mux the narration.

Outputs: narration.wav, captioned_video.mp4, final_video_captioned.mp4
"""
import json, os, subprocess, sys, urllib.request

import cv2
import content as C
import render_video as RV

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE = os.environ.get("ELEVENLABS_VOICE", "pNInz6obpgDQGcFmaJgB")
MODEL = "eleven_multilingual_v2"
FPS = RV.FPS
DUR = RV.DUR
NF = RV.NF
WORK = "/tmp/opencode/eleven/build"
os.makedirs(WORK, exist_ok=True)


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def ffprobe_duration(path):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path]))


def gen_segment(seg, path):
    body = json.dumps({
        "text": seg["text"],
        "model_id": MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8,
                           "style": 0.35, "use_speaker_boost": True},
    }).encode()
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}"
           f"?output_format=mp3_44100_128")
    req = urllib.request.Request(url, data=body, headers={
        "xi-api-key": KEY, "Content-Type": "application/json",
        "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req) as r:
        open(path, "wb").write(r.read())


def trim_silence(src, dst):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af",
         "silenceremove=start_periods=1:start_threshold=-35dB,"
         "areverse,silenceremove=start_periods=1:start_threshold=-35dB,"
         "areverse", "-ar", "44100", "-ac", "1", dst])


def build_narration():
    segs = json.load(open(os.path.join(HERE, "voiceover_script.json")))["segments"]
    clips, temps = [], []
    for s in segs:
        mp3 = os.path.join(WORK, f"seg_{s['id']:02d}.mp3")
        if not os.path.exists(mp3):
            gen_segment(s, mp3)
        wav = os.path.join(WORK, f"seg_{s['id']:02d}.wav")
        trim_silence(mp3, wav)
        d = ffprobe_duration(wav)
        allowed = (s["end"] - s["start"]) - s["pause_after"]
        ratio = d / allowed if allowed > 0 else 1.0
        tempo = max(1.0, ratio)
        clips.append((s, wav, d, allowed, tempo))
        print(f"seg {s['id']}: {d:.2f}s -> allowed {allowed:.2f}s "
              f"(tempo {tempo:.2f}x)", flush=True)

    # filter_complex: stretch to fit, pad to the full window, delay to start,
    # then pad every track to the full duration and mix.
    parts, labels = [], []
    for i, (s, wav, d, allowed, tempo) in enumerate(clips):
        start = s["start"]
        window = s["end"] - s["start"]
        chain = []
        if tempo > 1.0:
            chain.append(f"atempo={tempo:.4f}")
        chain += [f"atrim=0:{allowed:.4f}",
                  f"apad=whole_dur={window:.4f}",
                  f"atrim=0:{window:.4f}",
                  f"adelay={int(round(start * 1000))}",
                  f"apad=whole_dur={DUR:.4f}"]
        parts.append(f"[{i}:a]" + ",".join(chain) + f"[a{i}]")
        labels.append(f"[a{i}]")
    fc = ";".join(parts) + ";" + "".join(labels) + \
         f"amix=inputs={len(clips)}:normalize=0,pan=stereo|c0=c0|c1=c0," \
         f"loudnorm=I=-16:TP=-1.5:LRA=11"

    inputs = []
    for i, (s, wav, d, allowed, tempo) in enumerate(clips):
        inputs += ["-i", wav]
    out = os.path.join(HERE, "narration.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", fc, "-ar", "44100", "-ac", "2", out])
    print("narration ->", out, flush=True)


def build_captioned_video():
    src = os.path.join(HERE, "final_video.mp4")
    out = os.path.join(HERE, "captioned_video.mp4")
    cap = cv2.VideoCapture(src)

    def frames():
        i = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            RV.captions(fr, i / FPS)
            yield i, fr
            i += 1

    RV.encode(out, frames())
    print("captioned ->", out, flush=True)
    return out


def mux(video, audio):
    out = os.path.join(HERE, "final_video_captioned.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", audio,
         "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-shortest", out])
    print("final ->", out, flush=True)


if __name__ == "__main__":
    if not KEY:
        sys.exit("ELEVENLABS_API_KEY is not set")
    build_narration()
    v = build_captioned_video()
    mux(v, os.path.join(HERE, "narration.wav"))
