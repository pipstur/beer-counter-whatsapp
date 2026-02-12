INITIAL_BEER_COUNT = 240
CACHE_TTL_SEC = 300
WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ACHIEVEMENT_INFO = {
    "Noćna ptica 🦉": {
        "description": "Najviše popijenih piva između 23:00 i 04:00.",
    },
    "Ranoranilac 🌅": {
        "description": "Najviše popijenih piva između 04:00 i 11:00.",
    },
    "Vikendaš 🏖️": {
        "description": "Najviše piva petkom uveče i tokom vikenda.",
    },
    "Sprinter ⚡": {
        "description": "Najviše piva u jednoj sesiji (razmak ≤ 3h).",
    },
    "Maratonac 🏃": {
        "description": "Najduži niz dana sa bar jednim pivom.",
    },
    "Povratak kralja 👑": {
        "description": "Najveći povratak nakon ≥7 dana pauze (u 3 dana).",
    },
}

AGG_FREQ_MAP = {
    "Hour": "h",
    "Day": "D",
    "Week": "W",
}
MAX_BEERS_PER_ENTRY = 10
