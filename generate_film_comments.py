"""
One-off helper: generate FB comments for queued IG+FB reels.
Each comment references the reel's topic and ends with a link to a related published video
(or the FB page profile if no related video exists).

Run:  python3 generate_film_comments.py [--dry-run] [--account-id N] [--limit N]
"""

import argparse
import re
import sys
import sqlite3
from collections import defaultdict
from random import Random

import database as db


PAGE_PROFILES = {
    1: "https://www.facebook.com/1026165970576023",  # Świadek Dziejów
    2: "https://www.facebook.com/966442296563024",   # Świadek Jutra
    4: "https://www.facebook.com/103636161483247",   # RolePlayingLife IG+FB
    5: "https://www.facebook.com/1030846836785973",  # crewly
}

YT_CHANNEL_PROFILES = {
    3: "https://www.youtube.com/@RolePlayingLife",   # RolePlayingLife YouTube
}


# Topic-aware nice phrasing for the prefix
TOPIC_NAMES = {
    "iran": "Iran/Persja",
    "prl": "PRL",
    "polskaukraina": "Polska–Ukraina",
    "polskarosja": "Polska–Rosja",
    "polskaniemcy": "Polska–Niemcy",
    "polskaszwecja": "Polska–Szwecja",
    "polskaturcja": "Polska–Turcja",
    "polskamongoly": "Polska–Mongołowie",
    "polskairan": "Polska–Iran",
    "napoleon": "Napoleon",
    "kolaps": "kolaps cywilizacji",
    "zdrajcy": "zdrajcy w historii Polski",
    "bohaterowie": "polscy bohaterowie",
    "podziemie": "Polskie Państwo Podziemne",
    "przed1939": "ostatnie miesiące przed wojną",
    "potop": "potop szwedzki",
    "wojna1948": "wojna 1948 / Izrael",
    "pandemie": "pandemie w historii",
    "trump": "Trump i USA",
    "adhd": "ADHD",
    "ambergold": "Amber Gold",
    "zonda": "Zonda",
    "apple": "historia Apple",
    "tobacco": "przemysł tytoniowy",
    "tulipmania": "tulipomania",
    "centralia": "Centralia",
    "moai": "Wyspa Wielkanocna",
    "libertatia": "piracka utopia Libertatia",
    "kowloon": "Kowloon Walled City",
    "michniow": "Michniów",
    "panama": "Kanał Panamski",
    "smigus": "śmigus-dyngus",
    "slawik": "Henryk Sławik",
    "karski": "Jan Karski",
    "kopernik": "Kopernik-ekonomista",
    "obsolescence": "planowane starzenie produktów",
    "wolyn": "Wołyń",
    "wieliczka": "kopalnia w Wieliczce",
    "wykleci": "Żołnierze Wyklęci",
    "shackleton": "wyprawa Shackletona",
    "zegota": "Żegota",
    "zhenghe": "Zheng He",
    "zlotywiek": "polski Złoty Wiek",
    "zloty": "historia złota",
    "kadawerowy": "synod kadawerowy",
    "varosha": "Varosha",
    "tajlandia": "Tajlandia",
    "teheran": "konferencja teherańska",
    "sybir": "Sybir",
    "polscy": "Polacy w świecie",
    "v2most": "V2 i Most",
    "zanzibar": "Zanzibar",
    "zamojszczyzna": "Zamojszczyzna",
    "enigma": "Enigma",
    "caffaro": "Caffaro",
    "kakure": "Kakure Kirishitan",
    "ksiega": "Księga (zaginiona)",
    "husaria": "husaria",
    "kolumb": "Kolumb",
    "piraci": "piraci",
    "nazino": "wyspa Nazino",
}


def topic_label(prefix: str) -> str:
    return TOPIC_NAMES.get(prefix, prefix.replace("_", " "))


# Comment templates — rotated per-reel via seed.
# {hook} = something from the caption, {topic} = topic name, {url} = link
TEMPLATES = [
    "Cały kontekst tego wątku w osobnym materiale o {topic}",
    "Pełna historia {topic} — tutaj poszliśmy głębiej",
    "Kolejny odcinek z serii o {topic}",
    "Powiązany materiał z tej serii",
    "Więcej o {topic} w innym odcinku",
    "Jeśli ten wątek ciekawi — szerszy obraz tematu {topic} jest tutaj",
    "Rozwinięcie wątku w osobnym filmie",
    "Z tej samej serii — drugi odcinek",
    "Tu pełniejszy kontekst całego okresu",
]


def extract_hook(caption: str) -> str:
    """Return a clean opening sentence from the caption description, or '' if none fits.
    Skips bullet-point style captions (·, •, -lines) — those are factsheets, not prose."""
    if not caption:
        return ""
    text = caption.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Captions are typically "TITLE_LINE\n\nDESCRIPTION..." — drop the title line
    parts = text.split("\n\n", 1)
    if len(parts) == 2 and len(parts[0]) < 220:
        text = parts[1].strip()
    # Detect bullet-style captions — if most non-empty lines start with ·, •, or - then skip
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if lines:
        bullet_lines = sum(1 for ln in lines[:6] if ln[:2] in ("· ", "• ", "- ") or ln.startswith(("·", "•")))
        if bullet_lines >= 2:
            return ""
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Skip if text starts with a bullet character
    if text.startswith(("·", "•", "-")):
        return ""
    # Match the first sentence ending in . ! ? — must be 30..200 chars
    m = re.match(r"(.{30,200}?[\.\!\?])(?:\s|$)", text)
    if not m:
        return ""
    sent = m.group(1).strip()
    # Skip if hook contains bullet markers (mid-sentence factsheet glue)
    if "·" in sent or "•" in sent:
        return ""
    if not re.search(r"[\w\u00c0-\u017f][\.\!\?]$", sent):
        return ""
    if len(sent) < 40:
        return ""
    return sent


def filename_prefix(filename: str) -> str:
    base = filename.lower()
    m = re.match(r"^([a-z0-9]+)", base)
    return m.group(1) if m else ""


def build_link_pool() -> dict:
    """Build (account_id, prefix, platform) -> [list of published video URLs].
       platform = 'fb' or 'yt'."""
    pool = defaultdict(list)
    with db.get_db() as conn:
        # FB published reels
        rows = conn.execute(
            "SELECT account_id, filename, fb_permalink FROM videos "
            "WHERE status='published' AND fb_permalink IS NOT NULL AND fb_permalink != ''"
        ).fetchall()
        for r in rows:
            if r["fb_permalink"].rstrip("/").endswith("/videos"):
                continue
            p = filename_prefix(r["filename"])
            if p and p != "fb":
                pool[(r["account_id"], p, "fb")].append(r["fb_permalink"])
        # YT published shorts
        rows = conn.execute(
            "SELECT account_id, filename, yt_url FROM videos "
            "WHERE status='published' AND yt_url IS NOT NULL AND yt_url != ''"
        ).fetchall()
        for r in rows:
            p = filename_prefix(r["filename"])
            if p and p != "fb":
                pool[(r["account_id"], p, "yt")].append(r["yt_url"])
    return pool


def pick_link(rng: Random, account_id: int, prefix: str, this_filename: str,
              link_pool: dict, platform: str, source_film_url: str = None) -> tuple:
    """Return (url, kind, topic_gen, topic_loc).
       platform = 'fb' or 'yt' — affects link priority and fallbacks.
       kind in 'source_film' / 'long_fb' / 'long_yt' / 'related_reel' / 'page_profile'."""
    from long_film_map import get_long_film_link
    long_url, long_kind, topic_gen, topic_loc = get_long_film_link(prefix, account_id, platform)
    # 1. Configured source_film with permalink (highest priority)
    if source_film_url:
        return source_film_url, "source_film", topic_gen, topic_loc
    # 2. Curated long film mapping
    if long_url:
        return long_url, long_kind, topic_gen, topic_loc
    # 3. Other published video with same prefix on same account+platform
    candidates = link_pool.get((account_id, prefix, platform), [])
    if candidates:
        return rng.choice(candidates), "related_reel", topic_gen, topic_loc
    # 4. Channel/page profile
    if platform == "yt":
        return YT_CHANNEL_PROFILES.get(account_id, ""), "page_profile", topic_gen, topic_loc
    return PAGE_PROFILES.get(account_id, ""), "page_profile", topic_gen, topic_loc


def build_comment(rng: Random, video: dict, link: str, link_kind: str,
                  topic_gen: str, topic_loc: str) -> str:
    hook = extract_hook(video.get("caption") or "") if rng.random() < 0.65 else ""

    # Each invitation specifies which case to use via {gen} or {loc} placeholders.
    if link_kind in ("long_fb", "long_yt", "source_film"):
        invitations = [
            "Pełna historia {gen} w długim filmie",
            "Cała historia {gen} — w pełnym odcinku",
            "Pełen kontekst {gen} w długim filmie",
            "Cały film o {loc} — szerszy obraz",
            "Tu pełna opowieść o {loc}",
            "Pogłębiona historia {gen}",
            "Więcej w pełnym odcinku o {loc}",
            "Cała opowieść o {loc} w pełnym filmie",
        ]
    elif link_kind == "page_profile":
        invitations = [
            "Cała seria o {loc} czeka na profilu — zaglądnij",
            "Więcej odcinków z tej serii znajdziesz na profilu",
            "Reszta serii o {loc} — na profilu",
            "Po więcej o {loc} zaglądnij na profil",
            "Kolejne odcinki tej serii publikujemy regularnie — profil",
            "Cykl o {loc} ciągniemy dalej — śledź profil",
        ]
    else:  # related_reel
        invitations = [
            "Powiązany odcinek o {loc}",
            "Więcej w innym odcinku o {loc}",
            "Z tej samej serii — kolejny odcinek",
            "Tu poszliśmy z tym dalej",
            "Rozwinięcie wątku w innym filmie",
        ]
    invitation = rng.choice(invitations).format(
        gen=topic_gen or "tego tematu",
        loc=topic_loc or "tym temacie",
    )
    if hook:
        return f"{hook} {invitation}:\n{link}"
    return f"{invitation}:\n{link}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--platform", choices=["fb", "yt", "both"], default="both",
                        help="Which platform's comments to generate")
    args = parser.parse_args()

    link_pool = build_link_pool()
    print(f"Link pool: {sum(len(v) for v in link_pool.values())} URLs in "
          f"{len(link_pool)} groups")

    # Cache of source film URLs per platform
    film_fb_links = {}
    film_yt_links = {}
    for f in db.get_films():
        if f.get("fb_permalink"):
            film_fb_links[f["id"]] = f["fb_permalink"]
        if f.get("yt_url"):
            film_yt_links[f["id"]] = f["yt_url"]

    # Build account_type lookup
    accounts = {a["id"]: a for a in db.get_accounts()}

    # Build the list of work items: (video, platform, comment_field)
    work = []
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE status='queued' ORDER BY account_id, queue_position"
        ).fetchall()
    for r in rows:
        v = dict(r)
        if args.account_id and v["account_id"] != args.account_id:
            continue
        acc = accounts.get(v["account_id"])
        if not acc:
            continue
        # FB comment for IG+FB reels with target_fb=1
        if (acc["type"] == "instagram_facebook" and v.get("target_fb")
                and v.get("video_type") in ("reel", "story")):
            if args.platform in ("fb", "both"):
                if args.overwrite or not (v.get("fb_comment_text") or "").strip():
                    work.append((v, "fb", "fb_comment_text"))
        # YT comment for YouTube videos
        elif acc["type"] == "youtube":
            if args.platform in ("yt", "both"):
                if args.overwrite or not (v.get("yt_comment_text") or "").strip():
                    work.append((v, "yt", "yt_comment_text"))

    if args.limit:
        work = work[:args.limit]

    print(f"Work items: {len(work)}")
    counts = {}
    written = 0

    for v, platform, field in work:
        prefix = filename_prefix(v["filename"])
        rng = Random(f"{v['id']}_{platform}".__hash__())

        source_url = None
        if v.get("source_film_id"):
            cache = film_yt_links if platform == "yt" else film_fb_links
            source_url = cache.get(v["source_film_id"])

        link, kind, topic_gen, topic_loc = pick_link(
            rng, v["account_id"], prefix, v["filename"], link_pool, platform, source_url
        )
        if not link:
            continue

        if not topic_gen:
            topic_gen = topic_label(prefix)
        if not topic_loc:
            topic_loc = topic_label(prefix)

        text = build_comment(rng, v, link, kind, topic_gen, topic_loc)
        key = f"{platform}:{kind}"
        counts[key] = counts.get(key, 0) + 1
        written += 1

        if args.dry_run:
            print(f"\n[{v['id']}] {v['filename']}  ({platform}:{kind})")
            print(f"  → {text}")
        else:
            db.update_video(v["id"], {field: text})

    print(f"\nDone. Written: {written}")
    print(f"  Breakdown: {counts}")
    if args.dry_run:
        print("(dry-run)")


if __name__ == "__main__":
    main()
