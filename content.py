"""Single source of truth for narration + captions.
render_video.py, make_text_assets.py and the QC script all read from here,
so the voiceover JSON, SRT and burned-in captions can never drift apart."""

DURATION = 54.0  # seconds (1620 frames @ 30 fps)

# id, start, end, text, emotion, delivery, pause_after
NARRATION = [
    (1, 0.0, 5.2,
     "Over twelve thousand kilometres apart. Two nations. One war, over a few windswept islands.",
     "dramatic", "Strong, low opening hook; slight pause after 'apart' and after 'nations'", 0.2),
    (2, 5.4, 12.4,
     "The Falklands, called Las Malvinas in Argentina, lie about 480 kilometres off its coast. Britain has ruled them since 1833.",
     "authoritative", "Calm, informative; let 'Las Malvinas' land clearly", 0.2),
    (3, 12.4, 17.6,
     "On 2 April 1982, Argentina invaded the Falklands. A day later, it seized South Georgia.",
     "tense", "Build tension; short beat before 'A day later'", 0.2),
    (4, 17.6, 24.0,
     "Britain sent a task force south on 5 April. By 26 April, South Georgia was back under British control.",
     "serious", "Steady and purposeful", 0.2),
    (5, 24.0, 30.0,
     "On 21 May, British troops landed at San Carlos, then advanced across East Falkland towards Stanley.",
     "intense", "Driving pace, slightly faster through 'advanced'", 0.2),
    (6, 30.0, 35.0,
     "On 14 June, Argentine forces in Stanley surrendered. The war had lasted 74 days.",
     "solemn", "Slow down on 'surrendered'; pause before '74 days'", 0.3),
    (7, 35.0, 41.5,
     "649 Argentine and 255 British servicemen died, along with three islanders.",
     "somber", "Measured, respectful, no drama in the numbers", 0.4),
    (8, 41.5, 46.0,
     "In 2013, 99.8 percent of islanders voted to stay British.",
     "matter-of-fact", "Clear and neutral", 0.3),
    (9, 46.0, 53.0,
     "Argentina still claims the islands. Britain says the islanders decide. More than four decades on, the dispute is not settled.",
     "reflective", "Slow, weighty finish; long pause before the last sentence", 0.0),
]

# (start, end, line1, line2)  markup: {g:gold} {r:red} {e:emerald}
CAPTIONS = [
    (0.3, 2.7, "Over {g:12,000 km} apart,", "two nations."),
    (2.7, 5.3, "One war over a few", "{g:windswept islands}."),
    (5.5, 8.4, "The {g:Falkland Islands} —", "{g:Las Malvinas} to Argentines"),
    (8.4, 10.5, "About {g:480 km} from", "Argentina's coast"),
    (10.5, 12.3, "{r:British} since {g:1833}", ""),
    (12.5, 15.2, "{g:2 April 1982}", "{e:Argentina} invades"),
    (15.3, 17.5, "A day later:", "{g:South Georgia} seized"),
    (17.7, 21.4, "{r:Britain} sends a", "task force south"),
    (21.6, 24.0, "{g:26 April}:", "South Georgia retaken"),
    (24.1, 27.2, "{g:21 May}: British troops", "land at {g:San Carlos}"),
    (27.2, 30.0, "Advance on", "{g:Stanley}"),
    (30.1, 32.8, "{g:14 June}:", "{e:Argentina} surrenders"),
    (32.8, 35.0, "The war lasted", "{g:74 days}"),
    (35.1, 38.2, "{e:649 Argentine} and", "{r:255 British} servicemen"),
    (38.2, 41.4, "Plus {g:3 islanders}", "killed"),
    (41.6, 45.8, "{g:2013 referendum}:", "{g:99.8%} stay British"),
    (46.2, 49.2, "{e:Argentina} still claims", "the islands"),
    (49.3, 51.8, "{r:Britain} says the", "islanders decide"),
    (51.9, 53.4, "A dispute still", "{g:unsettled}"),
]

# HUD date cards: (start, end, date, label)
EVENTS = [
    (12.4, 15.2, "2 APRIL 1982", "ARGENTINA INVADES THE FALKLANDS"),
    (15.2, 17.6, "3 APRIL", "SOUTH GEORGIA SEIZED"),
    (17.6, 21.7, "5 APRIL", "BRITISH TASK FORCE SAILS"),
    (21.7, 24.0, "26 APRIL", "SOUTH GEORGIA RETAKEN"),
    (24.0, 27.2, "21 MAY", "BRITISH LANDING AT SAN CARLOS"),
    (27.2, 30.0, "LATE MAY – JUNE", "BRITISH ADVANCE ON STANLEY"),
    (30.0, 35.0, "14 JUNE", "ARGENTINE SURRENDER IN STANLEY"),
]
