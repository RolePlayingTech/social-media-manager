"""Regression tests for safe, predictable queue interleaving (stdlib only)."""

import itertools
import unittest

from interleave_queue import adjacency_count, filename_prefix, interleave


def make_items(counts):
    return [
        {"topic": topic, "sequence": index}
        for topic, count in enumerate(counts)
        for index in range(count)
    ]


def topic(item):
    return item["topic"]


class QueueInterleaveTests(unittest.TestCase):
    def test_empty_and_single_topic(self):
        self.assertEqual(interleave([], topic), [])
        items = make_items((4,))
        self.assertEqual(interleave(items, topic), items)

    def test_no_avoidable_adjacencies(self):
        # In an optimal arrangement, the largest bucket forces exactly
        # max(0, 2 * largest - total - 1) adjacent equal-key pairs.
        for counts in itertools.product(range(5), repeat=3):
            with self.subTest(counts=counts):
                items = make_items(counts)
                ordered = interleave(items, topic)
                self.assertEqual(len(ordered), len(items))
                expected = max(0, 2 * max(counts) - sum(counts) - 1)
                self.assertEqual(adjacency_count(ordered, topic), expected)

    def test_original_order_within_each_topic_is_preserved(self):
        items = make_items((5, 3, 2, 1))
        ordered = interleave(items, topic)
        self.assertEqual({id(item) for item in ordered}, {id(item) for item in items})
        for key in range(4):
            self.assertEqual(
                [item["sequence"] for item in ordered if topic(item) == key],
                [item["sequence"] for item in items if topic(item) == key],
            )
        self.assertEqual(items, make_items((5, 3, 2, 1)))

    def test_determinism_and_none_key(self):
        items = [{"topic": key} for key in (None, "a", "b", None, "a", "b")]
        first = interleave(items, topic, seed=123)
        self.assertEqual(first, interleave(items, topic, seed=123))
        self.assertEqual(adjacency_count(first, topic), 0)

    def test_filename_prefix(self):
        self.assertEqual(filename_prefix("Cats_001.MP4"), "cats")
        self.assertEqual(filename_prefix(""), "")
        self.assertEqual(filename_prefix(None), "")


if __name__ == "__main__":
    unittest.main()
