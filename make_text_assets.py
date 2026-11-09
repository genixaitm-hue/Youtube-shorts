#!/usr/bin/env python3
"""Generates voiceover_script.json, narration.txt and captions.srt from content.py."""
import json, re, os
import content as C
H = os.path.dirname(os.path.abspath(__file__))

def strip(s): return re.sub(r"\{\w:([^}]*)\}", r"\1", s)
def ts(x):
    ms = int(round(x * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

segs = [dict(id=i, start=a, end=b, text=t, emotion=e, delivery=d, pause_after=p) for i, a, b, t, e, d, p in C.NARRATION]
json.dump(dict(project="Geopolitical Shorts", language="English",
               voice_style="Professional cinematic documentary narrator (British or neutral English)",
               tone="Engaging, serious, authoritative", speed=1.0, total_duration_seconds=C.DURATION,
               segments=segs), open(f"{H}/voiceover_script.json", "w"), indent=2, ensure_ascii=False)
open(f"{H}/narration.txt", "w").write("\n\n".join(s["text"] for s in segs) + "\n")
out = []
for n, (a, b, l1, l2) in enumerate(C.CAPTIONS, 1):
    out.append(f"{n}\n{ts(a)} --> {ts(b)}\n{strip(l1)}" + (f"\n{strip(l2)}" if l2 else "") + "\n")
open(f"{H}/captions.srt", "w").write("\n".join(out))
print("ok", len(segs), "segments;", len(C.CAPTIONS), "captions")
