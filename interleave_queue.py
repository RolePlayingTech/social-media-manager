"""
Interleave the queue for an account so the same topic prefix doesn't appear
back-to-back. Preserves original relative order within each prefix bucket.

Run: python3 interleave_queue.py [--account-id N] [--dry-run]
"""

import argparse
import re
import sys
from collections import defaultdict, OrderedDict

import database as db


def filename_prefix(filename: str) -> str:
    base = (filename or "").lower()
    m = re.match(r"^([a-z0-9]+)", base)
    return m.group(1) if m else ""


def interleave(items: list, key_fn, seed: int = 42) -> list:
    """Return items reordered so consecutive items have different keys when possible.
    Picks randomly from top-K largest buckets that aren't the last key, weighted by size.
    Preserves original relative order within each bucket."""
    import random
    rng = random.Random(seed)
    buckets = OrderedDict()
    for it in items:
        k = key_fn(it)
        buckets.setdefault(k, []).append(it)

    out = []
    last_key = None
    while any(buckets.values()):
        candidates = [(k, len(v)) for k, v in buckets.items() if v and k != last_key]
        if not candidates:
            # Only same-key bucket left
            chosen = next(k for k, v in buckets.items() if v)
        else:
            # Sort by remaining size desc; weighted random over top-N largest
            candidates.sort(key=lambda x: -x[1])
            top = candidates[:5]
            weights = [c[1] for c in top]
            chosen = rng.choices([c[0] for c in top], weights=weights, k=1)[0]
        out.append(buckets[chosen].pop(0))
        last_key = chosen
    return out


def adjacency_count(items: list, key_fn) -> int:
    """Number of consecutive same-key adjacencies."""
    return sum(
        1 for a, b in zip(items, items[1:])
        if key_fn(a) == key_fn(b)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", type=int, default=None,
                        help="Restrict to one account (default: all queued accounts)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT id, account_id, filename, queue_position FROM videos "
            "WHERE status='queued' ORDER BY account_id, queue_position"
        ).fetchall()

    by_account = defaultdict(list)
    for r in rows:
        if args.account_id and r["account_id"] != args.account_id:
            continue
        by_account[r["account_id"]].append(dict(r))

    for acc_id, items in by_account.items():
        before_adj = adjacency_count(items, lambda v: filename_prefix(v["filename"]))
        ordered = interleave(items, lambda v: filename_prefix(v["filename"]))
        after_adj = adjacency_count(ordered, lambda v: filename_prefix(v["filename"]))
        print(f"acc={acc_id}: {len(items)} items, "
              f"adjacent same-prefix: {before_adj} → {after_adj}")

        if args.dry_run:
            print("  First 15 of new order:")
            for i, v in enumerate(ordered[:15]):
                print(f"    {i+1:>3}. [{filename_prefix(v['filename']):>14}] {v['filename']}")
        else:
            with db.get_db() as conn:
                for new_pos, v in enumerate(ordered):
                    if v["queue_position"] != new_pos:
                        conn.execute(
                            "UPDATE videos SET queue_position=?, updated_at=datetime('now') "
                            "WHERE id=?", (new_pos, v["id"])
                        )
            print(f"  ✓ Reordered {len(ordered)} items")


if __name__ == "__main__":
    main()
