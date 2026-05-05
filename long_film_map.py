"""
Curated mapping: reel filename prefix -> long film links.
Built by inspecting long_videos_cache.json (run fetch_long_videos.py first).

Each entry maps to a dict with:
  fb_by_account: {account_id: url} - prefer FB link from same account when reel publishes there
  yt: url                          - YouTube fallback (RolePlayingLife channel)
  topic_human: str                 - GENITIVE form for "historia X" / "kontekst X" templates
  topic_loc: str                   - LOCATIVE form for "o X" templates
"""

PREFIX_TO_LONG = {
    "iran": {
        "fb_by_account": {4: "https://www.facebook.com/reel/942697655137347"},
        "yt": "https://www.youtube.com/watch?v=cOvKlHGx4r0",
        "topic_human": "Iranu", "topic_loc": "Iranie",
    },
    "polskairan": {
        "fb_by_account": {4: "https://www.facebook.com/reel/942697655137347"},
        "yt": "https://www.youtube.com/watch?v=cOvKlHGx4r0",
        "topic_human": "Iranu i jego relacji z Polską", "topic_loc": "Iranie",
    },
    "polskaukraina": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1515932879962744"},
        "yt": "https://www.youtube.com/watch?v=o8cWDL_R9Js",
        "topic_human": "Polski i Ukrainy", "topic_loc": "Polsce i Ukrainie",
    },
    "prl": {
        "fb_by_account": {1: "https://www.facebook.com/reel/2360690767676895"},
        "yt": "https://www.youtube.com/watch?v=LCWsixacMQ8",
        "topic_human": "PRL-u", "topic_loc": "PRL-u",
    },
    "bohaterowie": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1472585461233937"},
        "yt": "https://www.youtube.com/watch?v=UNQS-G3ouzg",
        "topic_human": "polskich bohaterów II wojny", "topic_loc": "polskich bohaterach II wojny",
    },
    "wojna1948": {
        "fb_by_account": {},
        "yt": "https://www.youtube.com/watch?v=K6EDQlJ9BDU",
        "topic_human": "I wojny izraelsko-arabskiej 1948", "topic_loc": "I wojnie izraelsko-arabskiej 1948",
    },
    "napoleon": {
        "fb_by_account": {1: "https://www.facebook.com/reel/951713420812868"},
        "yt": "https://www.youtube.com/watch?v=qT8JFazdrFM",
        "topic_human": "Napoleona", "topic_loc": "Napoleonie",
    },
    "zdrajcy": {
        "fb_by_account": {},
        "yt": "https://www.youtube.com/watch?v=7DAdQi82F8c",
        "topic_human": "zdrajców Polski", "topic_loc": "zdrajcach Polski",
    },
    "pandemie": {
        "fb_by_account": {4: "https://www.facebook.com/reel/1590882508685087"},
        "yt": "https://www.youtube.com/watch?v=C1heSaL8joo",
        "topic_human": "pandemii w historii", "topic_loc": "pandemiach w historii",
    },
    "przed1939": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1603406084296862"},
        "yt": "https://www.youtube.com/watch?v=Oen7QOzVdkE",
        "topic_human": "ostatnich miesięcy przed II wojną", "topic_loc": "ostatnich miesiącach przed II wojną",
    },
    "adhd": {
        "fb_by_account": {4: "https://www.facebook.com/reel/2239093206916609"},
        "yt": "https://www.youtube.com/watch?v=L7vmBSxlneg",
        "topic_human": "ADHD", "topic_loc": "ADHD",
    },
    "ambergold": {
        "fb_by_account": {4: "https://www.facebook.com/reel/3538780306260097"},
        "yt": "https://www.youtube.com/watch?v=8NC4dJm_QAQ",
        "topic_human": "Amber Gold", "topic_loc": "Amber Gold",
    },
    "podziemie": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1280191430322806"},
        "yt": "https://www.youtube.com/watch?v=Pdjci3lPBEQ",
        "topic_human": "Polskiego Państwa Podziemnego", "topic_loc": "Polskim Państwie Podziemnym",
    },
    "potop": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1262705755848526"},
        "yt": "https://www.youtube.com/watch?v=Jgg6tbGuZdA",
        "topic_human": "potopu szwedzkiego", "topic_loc": "potopie szwedzkim",
    },
    "zonda": {
        "fb_by_account": {4: "https://www.facebook.com/reel/4492991967624470"},
        "yt": "https://www.youtube.com/watch?v=t4g5XyvTYxY",
        "topic_human": "afery Zondacrypto", "topic_loc": "aferze Zondacrypto",
    },
    "trump": {
        "fb_by_account": {4: "https://www.facebook.com/reel/1274847438192989"},
        "yt": "https://www.youtube.com/watch?v=s007xlIF_vA",
        "topic_human": "Donalda Trumpa", "topic_loc": "Donaldzie Trumpie",
    },
    "kolaps": {
        "fb_by_account": {1: "https://www.facebook.com/reel/925338036787577"},
        "yt": None,
        "topic_human": "kolapsu cywilizacji", "topic_loc": "kolapsie cywilizacji",
    },
    "apple": {
        "fb_by_account": {4: "https://www.facebook.com/reel/2659953851044067"},
        "yt": "https://www.youtube.com/watch?v=y3UcFTXc68Q",
        "topic_human": "polskiej informatyki", "topic_loc": "polskiej informatyce",
    },
    "enigma": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1683972073052991"},
        "yt": "https://www.youtube.com/watch?v=DEkShMN4F-A",
        "topic_human": "złamania Enigmy", "topic_loc": "złamaniu Enigmy",
    },
    "zloto": {
        "fb_by_account": {4: "https://www.facebook.com/reel/974228871728208"},
        "yt": None,
        "topic_human": "ucieczki polskich skarbów", "topic_loc": "ucieczce polskich skarbów",
    },
    "zlotywiek": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1251373723866322/"},
        "yt": "https://www.youtube.com/watch?v=R2SF9HOGxrM",
        "topic_human": "polskiego Złotego Wieku", "topic_loc": "polskim Złotym Wieku",
    },
    # ── New series (added 2026-04-26) ──────────────────────────────
    # 'pj' = Persja/Iran (uses same long film as 'iran')
    "pj": {
        "fb_by_account": {4: "https://www.facebook.com/reel/942697655137347"},
        "yt": "https://www.youtube.com/watch?v=cOvKlHGx4r0",
        "topic_human": "Iranu i Persji", "topic_loc": "Iranie i Persji",
    },
    # 'w48n' = nowa seria o wojnie 1948 (ta sama tematyka co 'wojna1948')
    "w48n": {
        "fb_by_account": {},
        "yt": "https://www.youtube.com/watch?v=K6EDQlJ9BDU",
        "topic_human": "I wojny izraelsko-arabskiej 1948", "topic_loc": "I wojnie izraelsko-arabskiej 1948",
    },
    # 'cf' = cancer fighters (film 12: 150 MILIONÓW W 9 DNI)
    "cf": {
        "fb_by_account": {4: "https://www.facebook.com/reel/1452455632610527/"},
        "yt": "https://www.youtube.com/watch?v=GVUB_-hpzx8",
        "topic_human": "walki z rakiem",
        "topic_loc": "walce z rakiem",
    },
    # 'bd' = NARODZINY BUDDY — film 5 not yet published (no permalink)
    "bd": {
        "fb_by_account": {},
        "yt": None,
        "topic_human": "narodzin buddyzmu", "topic_loc": "narodzinach buddyzmu",
    },
    # 'cw' = WZLOT I UPADEK 5000 lat cywilizacji — film 6 not yet published
    "cw": {
        "fb_by_account": {},
        "yt": None,
        "topic_human": "5000 lat największych cywilizacji świata",
        "topic_loc": "5000 latach największych cywilizacji świata",
    },
    # 'rz' = ANATOMIA UPADKU Rzeczypospolitej — film 8 not yet published
    "rz": {
        "fb_by_account": {},
        "yt": None,
        "topic_human": "anatomii upadku I Rzeczypospolitej",
        "topic_loc": "anatomii upadku I Rzeczypospolitej",
    },
    # 'ue' = HISTORIA UNII EUROPEJSKIEJ — film 9 not yet published
    "ue": {
        "fb_by_account": {},
        "yt": None,
        "topic_human": "Unii Europejskiej", "topic_loc": "Unii Europejskiej",
    },
    # 'polskamongoly' → najazd mongolski + odbudowa Polski (Legnica 1241)
    "polskamongoly": {
        "fb_by_account": {1: "https://www.facebook.com/reel/1655229055496359/"},
        "yt": None,
        "topic_human": "najazdów mongolskich i odbudowy Polski",
        "topic_loc": "najazdach mongolskich i odbudowie Polski",
    },
    # przyszlosc — długi film opublikowany ręcznie na FB Świadek Jutra
    "pz": {
        "fb_by_account": {2: "https://fb.watch/GKZdvvlUHn/"},
        "yt": None,
        "topic_human": "przyszłości i prognoz na rok 2126",
        "topic_loc": "przyszłości i tym, co nas czeka w 2126",
    },
}

# For prefixes WITHOUT a curated long film, only provide topic naming (no link).
# Formatted as (prefix, topic_human, topic_loc).
TOPIC_ONLY = [
    ("obsolescence", "planowanego starzenia produktów", "planowanym starzeniu produktów"),
    ("tobacco", "przemysłu tytoniowego", "przemyśle tytoniowym"),
    ("tulipmania", "tulipomanii", "tulipomanii"),
    ("centralia", "Centralii", "Centralii"),
    ("moai", "Wyspy Wielkanocnej", "Wyspie Wielkanocnej"),
    ("libertatia", "pirackiej Libertatii", "pirackiej Libertatii"),
    ("kowloon", "Kowloon Walled City", "Kowloon Walled City"),
    ("michniow", "Michniowa", "Michniowie"),
    ("panama", "Kanału Panamskiego", "Kanale Panamskim"),
    ("smigus", "śmigusa-dyngusa", "śmigusie-dyngusie"),
    ("slawik", "Henryka Sławika", "Henryku Sławiku"),
    ("karski", "Jana Karskiego", "Janie Karskim"),
    ("kopernik", "Kopernika-ekonomisty", "Koperniku-ekonomiście"),
    ("wolyn", "Wołynia", "Wołyniu"),
    ("wieliczka", "kopalni w Wieliczce", "kopalni w Wieliczce"),
    ("wykleci", "Żołnierzy Wyklętych", "Żołnierzach Wyklętych"),
    ("shackleton", "wyprawy Shackletona", "wyprawie Shackletona"),
    ("zegota", "Żegoty", "Żegocie"),
    ("zhenghe", "Zheng He", "Zheng He"),
    ("kadawerowy", "synodu kadawerowego", "synodzie kadawerowym"),
    ("varosha", "Varoshy", "Varoshe"),
    ("nazino", "wyspy Nazino", "wyspie Nazino"),
    ("polskarosja", "stosunków Polska-Rosja", "stosunkach Polska-Rosja"),
    ("polskaniemcy", "stosunków Polska-Niemcy", "stosunkach Polska-Niemcy"),
    ("polskaszwecja", "stosunków Polska-Szwecja", "stosunkach Polska-Szwecja"),
    ("polskaturcja", "stosunków Polska-Turcja", "stosunkach Polska-Turcja"),
    # polskamongoly → handled below in PREFIX_TO_LONG (mapped to FB long film)
    ("husaria", "husarii", "husarii"),
    ("kolumb", "Kolumba", "Kolumbie"),
    ("piraci", "piractwa", "piractwie"),
    ("teheran", "konferencji teherańskiej", "konferencji teherańskiej"),
    ("sybir", "Syberii i zsyłek", "Syberii i zsyłkach"),
    ("polscy", "Polaków w świecie", "Polakach w świecie"),
    ("v2most", "akcji Most", "akcji Most"),
    ("zanzibar", "Zanzibaru", "Zanzibarze"),
    ("zamojszczyzna", "Zamojszczyzny", "Zamojszczyźnie"),
    ("caffaro", "Caffaro", "Caffaro"),
    ("kakure", "Kakure Kirishitan", "Kakure Kirishitan"),
    ("ksiega", "zaginionej księgi", "zaginionej księdze"),
    ("tajlandia", "Tajlandii", "Tajlandii"),
]

for pref, gen, loc in TOPIC_ONLY:
    PREFIX_TO_LONG[pref] = {
        "fb_by_account": {}, "yt": None,
        "topic_human": gen, "topic_loc": loc,
    }


def get_long_film_link(prefix: str, account_id: int, platform: str = "fb") -> tuple:
    """Return (url, kind, topic_human, topic_loc).
       platform='fb' prefers FB long video on the same account, then YT.
       platform='yt' prefers YouTube long video, ignores FB.
       kind in 'long_fb','long_yt' or None if no curated link."""
    entry = PREFIX_TO_LONG.get(prefix)
    if not entry:
        return None, None, None, None
    if platform == "yt":
        # For YouTube targets — prefer YT long film
        yt = entry.get("yt")
        if yt:
            return yt, "long_yt", entry["topic_human"], entry["topic_loc"]
        return None, None, entry.get("topic_human"), entry.get("topic_loc")
    # FB target — only same-account FB long film. NEVER fall back to YT
    # (FB users shouldn't be sent off-platform to YouTube).
    fb_url = entry["fb_by_account"].get(account_id)
    if fb_url:
        return fb_url, "long_fb", entry["topic_human"], entry["topic_loc"]
    return None, None, entry.get("topic_human"), entry.get("topic_loc")
