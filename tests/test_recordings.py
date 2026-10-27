import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

from yoin.library import load_library


class RecordingTests(unittest.TestCase):
    def test_committed_recordings_match_manifest_and_library(self):
        root = Path(__file__).resolve().parents[1]
        library = load_library(root / "library.json")
        manifest = json.loads((root / "sounds" / "recorded" / "sources.json").read_text())
        self.assertEqual(len(manifest["sources"]), 3)
        for source in manifest["sources"]:
            with self.subTest(sound=source["id"]):
                sound = library.sounds[source["id"]]
                self.assertFalse(sound.placeholder)
                self.assertIn(source["source_url"], sound.source)
                self.assertIn(source["license"], sound.license)
                path = root / source["output"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["output_sha256"])
                audio = library.audio(sound.id)
                self.assertEqual(audio.shape[1], 1)
                self.assertTrue(np.isfinite(audio).all())
                self.assertGreater(float(np.max(np.abs(audio))), 0)
