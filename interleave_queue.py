"""
Interleave the queue for an account so the same topic prefix doesn't appear
back-to-back. Preserves original relative order within each prefix bucket.

Run: python3 interleave_queue.py [--account-id N] [--dry-run] [--seed N]
"""

import argparse
import re
from collections import defaultdict, OrderedDict, deque
import heapq
import random

import database as db


def filename_prefix(filename: str) -> str:
    base = (filename or "").lower()
    m = re.match(r"^([a-z0-9]+)", base)
    return m.group(1) if m else ""


def interleave(items: list, key_fn, seed: int = 42) -> list:
    """Minimize adjacent matching keys while keeping each bucket in input order.

    Always select the largest remaining bucket that differs from the last key.
    Randomized tie-breaking is reproducible via seed. Unlike weighted
    sampling, this avoids preventable same-topic runs in uneven queues.
    """
    rng = random.Random(seed)
    buckets = OrderedDict()
    for item in items:
        buckets.setdefault(key_fn(item), deque()).append(item)

    # A fixed random tie order avoids comparing potentially different key types
    # inside the heap. Most importantly, it keeps repeated runs reproducible.
    keys = list(buckets)
    rng.shuffle(keys)
    priority = {key: index for index, key in enumerate(keys)}
    heap = [(-len(queue), priority[key], key) for key, queue in buckets.items()]
    heapq.heapify(heap)

    ordered = []
    last_key = object()  # Sentinel: None can be a legitimate key.
    while heap:
        candidate = heapq.heappop(heap)
        if candidate[2] == last_key and heap:
            alternative = heapq.heappop(heap)
            heapq.heappush(heap, candidate)
            candidate = alternative

        remaining, rank, key = candidate
        ordered.append(buckets[key].popleft())
        if remaining < -1:
            heapq.heappush(heap, (remaining + 1, rank, key))
        last_key = key

    return ordered


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
    parser.add_argument("--seed", type=int, default=42,
                        help="Reproducible tie-breaking seed (default: 42)")
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
        ordered = interleave(items, lambda v: filename_prefix(v["filename"]), seed=args.seed)
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
