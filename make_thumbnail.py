#!/usr/bin/env python3
"""thumbnail.png (1080x1920): hook frame without captions + big headline."""
import cv2, content as C
C.CAPTIONS = []
import render_video as RV
from render_video import render, text_sprite, blit, GOLD, WHITE
f = render(4.4)
cv2.rectangle(f, (0, 1040), (1080, 1560), (0, 0, 0), -1) if False else None
f = (f * 0.0 + f).astype('uint8')
# darken lower band for legibility
import numpy as np
band = np.zeros((1920, 1080, 1), np.float32); band[1000:1650] = (np.clip(np.linspace(0, 1, 650), 0, 1) ** 1.4 * .72)[:, None, None]; band[1650:] = .72
f = (f * (1 - band)).astype('uint8')
blit(f, text_sprite("THE FALKLANDS", 118, WHITE), 540, 1200)
blit(f, text_sprite("WAR", 190, GOLD), 540, 1355)
blit(f, text_sprite("74 DAYS  ·  UK vs ARGENTINA", 34, WHITE, "Medium", track=4), 540, 1500)
cv2.imwrite("thumbnail.png", f); print("thumbnail.png written")
