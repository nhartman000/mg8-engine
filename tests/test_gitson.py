import json
import tempfile
import unittest
from pathlib import Path

from mg8_engine.gitson import (
    CANON_REPOS,
    GitsonError,
    load_bundle,
    make_block,
    split_canon_bundle,
    write_parts,
)


def blocks(n, size=200):
    return [make_block(f"b{i}", f"Block {i}",
                       f"https://github.com/nhartman000/repo{i}",
                       ("x" * size)) for i in range(n)]


class GitsonTests(unittest.TestCase):
    def test_single_part_when_everything_fits(self):
        parts = split_canon_bundle(blocks(3), bundle_id="t", max_bytes=100_000)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["part"], "1.1")
        self.assertEqual(parts[0]["parts_total"], 1)
        self.assertEqual(len(parts[0]["blocks"]), 3)

    def test_splits_into_numbered_parts(self):
        parts = split_canon_bundle(blocks(6, size=800), bundle_id="t",
                                   max_bytes=3000, references=[])
        self.assertGreater(len(parts), 1)
        self.assertEqual([p["part"] for p in parts],
                         [f"1.{i}" for i in range(1, len(parts) + 1)])
        self.assertTrue(all(p["parts_total"] == len(parts) for p in parts))

    def test_every_part_respects_max_bytes(self):
        max_bytes = 3000
        parts = split_canon_bundle(blocks(6, size=800), bundle_id="t",
                                   max_bytes=max_bytes, references=[])
        for p in parts:
            size = len(json.dumps(p, ensure_ascii=False, indent=2)
                       .encode("utf-8")) + 1
            self.assertLessEqual(size, max_bytes)

    def test_nothing_lost_across_split(self):
        src = blocks(6, size=800)
        parts = split_canon_bundle(src, bundle_id="t", max_bytes=3000,
                                   references=[])
        rejoined = [b for p in parts for b in p["blocks"]]
        self.assertEqual(rejoined, src)

    def test_oversized_block_demoted_to_reference_not_truncated(self):
        big = make_block("huge", "Huge", "https://github.com/nhartman000/huge",
                         "y" * 10_000)
        parts = split_canon_bundle([big], bundle_id="t", max_bytes=2000,
                                   references=[])
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["blocks"], [])
        self.assertIn("huge", parts[0]["demoted"])
        self.assertIn("https://github.com/nhartman000/huge",
                      parts[0]["references"])

    def test_default_references_are_canon_repos(self):
        parts = split_canon_bundle(blocks(1), bundle_id="t", max_bytes=100_000)
        self.assertEqual(parts[0]["references"], CANON_REPOS)
        self.assertIn("https://github.com/nhartman000/nych", CANON_REPOS)

    def test_write_and_load_roundtrip(self):
        src = blocks(6, size=800)
        parts = split_canon_bundle(src, bundle_id="t", max_bytes=3000,
                                   references=["https://example.com/r"])
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_parts(parts, tmp)
            self.assertTrue(all(p.name.endswith(".gitson") for p in paths))
            self.assertEqual(paths[0].name, "canon.1.1.gitson")
            bundle = load_bundle(paths)
        self.assertEqual(bundle["blocks"], src)
        self.assertEqual(bundle["bundle_id"], "t")
        self.assertIn("https://example.com/r", bundle["references"])

    def test_load_rejects_missing_part(self):
        parts = split_canon_bundle(blocks(6, size=800), bundle_id="t",
                                   max_bytes=3000, references=[])
        self.assertGreater(len(parts), 1)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_parts(parts, tmp)
            with self.assertRaises(GitsonError):
                load_bundle(paths[:-1])

    def test_load_rejects_mixed_bundles(self):
        a = split_canon_bundle(blocks(1), bundle_id="a", max_bytes=100_000)
        b = split_canon_bundle(blocks(1), bundle_id="b", max_bytes=100_000)
        with tempfile.TemporaryDirectory() as tmp:
            pa = write_parts(a, tmp, stem="a")
            pb = write_parts(b, tmp, stem="b")
            with self.assertRaises(GitsonError):
                load_bundle(pa + pb)

    def test_invalid_block_and_limit_rejected(self):
        with self.assertRaises(GitsonError):
            split_canon_bundle([{"block_id": "x"}], bundle_id="t",
                               max_bytes=1000)
        with self.assertRaises(GitsonError):
            split_canon_bundle(blocks(1), bundle_id="t", max_bytes=0)


if __name__ == "__main__":
    unittest.main()
