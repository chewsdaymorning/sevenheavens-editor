"""Real FFmpeg plumbing tests using generated fixtures, never AI acceptance."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.contracts import EditPlan, MusicPlacement, Shot, TextOverlay
from backend.media import (MediaCancelled, MediaError, UnsupportedColorError,
                           create_proxy, detect_reference_cuts, extract_music_map,
                           register_asset, sample_frames)
from backend.render import render_plan


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = Path(os.environ.get("SEVENHEAVENS_TEST_DATA_DIR", "data/test-fixtures"))
        runtime.mkdir(parents=True, exist_ok=True)
        cls.directory = Path(tempfile.mkdtemp(prefix="media-", dir=runtime)).resolve()
        cls.source = cls.directory / "source.mp4"
        cls.music = cls.directory / "music.wav"
        cls.offset = cls.directory / "offset.mp4"
        cls.vfr = cls.directory / "vfr.mp4"
        cls.command(["-f", "lavfi", "-i", "color=c=red:s=320x240:r=30:d=1",
                     "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=1",
                     "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_trc", "bt709",
                     "-color_primaries", "bt709", "-colorspace", "bt709", str(cls.source)])
        cls.command(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4", str(cls.music)])
        cls.command(["-itsoffset", "5", "-i", str(cls.source), "-c", "copy", "-copyts", str(cls.offset)])
        cls.command(["-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=2", "-vf",
                     "select='if(lt(t,1),not(mod(n,2)),1)'", "-fps_mode", "vfr", "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-color_trc", "bt709", str(cls.vfr)])

    @classmethod
    def command(cls, args):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + args,
                       check=True, capture_output=True, timeout=30)

    def asset(self, path=None):
        return register_asset(path or self.source)

    def plan(self, asset, *, music=None, text=False):
        return EditPlan(project_id="fixture-project", brief_id="fixture-project", mode="fixture",
                        width=1080, height=1920, fps_num=30, fps_den=1,
                        shots=[Shot(asset_id=asset.id, source_start_s=.2, source_end_s=.7,
                                    timeline_start_frame=0, timeline_end_frame=15,
                                    manual_override_reason="Generated red fixture; no semantic AI claim"),
                               Shot(asset_id=asset.id, source_start_s=1.2, source_end_s=1.7,
                                    timeline_start_frame=15, timeline_end_frame=30,
                                    manual_override_reason="Generated blue fixture; no semantic AI claim")],
                        music=MusicPlacement(asset_id=music.id, source_start_s=.5) if music else None,
                        text=[TextOverlay(text="Fixture only", start_frame=0, end_frame=15)] if text else [],
                        operations=["cut", "scale"] + (["music"] if music else []) + (["text"] if text else []))

    def test_registration_nonzero_pts_and_integrity(self):
        before = hashlib.sha256(self.offset.read_bytes()).hexdigest()
        asset = self.asset(self.offset)
        self.assertAlmostEqual(asset.stream_origin_s, 5, places=4)
        self.assertAlmostEqual(asset.duration_s, 2, places=3)
        self.assertEqual(asset.rate_mode, "cfr")
        samples = sample_frames(asset, self.directory / "samples", timestamps_s=[.2, 1.2])
        self.assertAlmostEqual(samples[0]["source_pts_s"], 5.2, places=4)
        self.assertTrue(Path(samples[0]["path"]).is_file())
        self.assertEqual(hashlib.sha256(self.offset.read_bytes()).hexdigest(), before)

    def test_vfr_proxy_maps_decoded_pts(self):
        asset = self.asset(self.vfr)
        self.assertEqual(asset.rate_mode, "vfr")
        proxy = create_proxy(asset, self.directory / "proxies")
        self.assertEqual(len(proxy.timestamp_mapping), len(asset.timestamp_mapping))
        self.assertTrue(Path(proxy.working_path).is_file())
        # Irregular source PTS remain irregular; no nominal-FPS reconstruction.
        self.assertEqual([p.source_s for p in proxy.timestamp_mapping],
                         [p.source_s for p in asset.timestamp_mapping])
        self.assertAlmostEqual(proxy.timestamp_mapping[-1].source_s,
                               proxy.timestamp_mapping[-1].working_s, places=3)

    def test_rotation_is_display_oriented_and_crop_is_explicit(self):
        rotated_path = self.directory / "rotated.mp4"
        self.command(["-display_rotation:v:0", "90", "-i", str(self.source), "-c", "copy", str(rotated_path)])
        asset = self.asset(rotated_path)
        self.assertEqual(abs(asset.rotation_degrees), 90)
        self.assertEqual((asset.width, asset.height), (240, 320))
        from backend.contracts import Crop
        plan = self.plan(asset).model_copy(deep=True, update={"width": 108, "height": 192})
        plan.shots[0].crop = Crop(x=.1, y=.1, width=.8, height=.8)
        with self.assertRaisesRegex(MediaError, "Crop not allowed"):
            render_plan(plan, {asset.id: asset}, self.directory / "crop-forbidden")
        plan.operations.append("crop")
        result = render_plan(plan, {asset.id: asset}, self.directory / "crop-allowed")
        self.assertEqual(result["qc"]["frame_count"], 30)

    def test_reference_cut_and_music_anchor_truthfulness(self):
        reference = register_asset(self.source, role="reference")
        cuts = detect_reference_cuts(reference, threshold=5)["cuts_s"]
        self.assertTrue(any(abs(t - 1) < .04 for t in cuts), cuts)
        music = register_asset(self.music, role="music")
        result = extract_music_map(music, excerpt_start_s=.5, duration_s=2, manual_anchors_s=[.25, 1.25])
        self.assertEqual(result["manual_anchors_s"], [.25, 1.25])
        self.assertFalse(result["beat_grid_verified"])
        with self.assertRaises(MediaError):
            extract_music_map(music, excerpt_start_s=3, duration_s=2)

    def test_actual_portrait_audio_render_and_source_cut_trace(self):
        asset = self.asset(self.offset)
        music = register_asset(self.music, role="music")
        result = render_plan(self.plan(asset, music=music), {asset.id: asset, music.id: music}, self.directory / "renders")
        manifest = json.loads(Path(result["manifest_path"]).read_text())
        self.assertEqual(manifest["qc"]["frame_count"], 30)
        self.assertEqual((manifest["qc"]["width"], manifest["qc"]["height"]), (1080, 1920))
        self.assertTrue(manifest["qc"]["has_audio"])
        self.assertEqual(manifest["operating_mode"], "fixture")
        self.assertEqual(manifest["sources"][asset.id]["stream_origin_s"], 5)
        # Inspect decoded pixels before/after the planned cut, beyond exit/QC.
        for timestamp, channel in [(0.2, 0), (.7, 2)]:
            decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", result["output_path"],
                                      "-ss", str(timestamp), "-vf", "crop=100:100:490:910,scale=1:1",
                                      "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                     capture_output=True, check=True, timeout=15).stdout
            self.assertGreater(decoded[channel], 200, (timestamp, list(decoded)))
        # Audio decodes to actual nonzero samples, rather than only a stream flag.
        audio = subprocess.run(["ffmpeg", "-v", "error", "-i", result["output_path"], "-vn",
                                "-f", "s16le", "-"], capture_output=True, check=True, timeout=15).stdout
        self.assertGreater(len(audio), 80000)
        self.assertTrue(any(audio))

    def test_reject_changed_source_bounds_color_and_cancel(self):
        asset = self.asset()
        plan = self.plan(asset)
        bad = plan.model_copy(deep=True)
        bad.shots[0].source_end_s = 30
        with self.assertRaisesRegex(MediaError, "outside"):
            render_plan(bad, {asset.id: asset}, self.directory / "invalid")
        with self.assertRaisesRegex(MediaError, "registered"):
            render_plan(plan, {}, self.directory / "invalid")
        hdr = asset.model_copy(update={"color_transfer": "smpte2084"})
        with self.assertRaises(UnsupportedColorError):
            render_plan(plan, {asset.id: hdr}, self.directory / "invalid")
        with self.assertRaises(MediaCancelled):
            render_plan(plan, {asset.id: asset}, self.directory / "cancel", cancel_check=lambda: True)
        changed = self.directory / "changed.mp4"
        shutil.copyfile(self.source, changed)
        changed_asset = register_asset(changed)
        with changed.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(MediaError, "changed"):
            render_plan(self.plan(changed_asset), {changed_asset.id: changed_asset}, self.directory / "invalid")

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not installed")
    def test_optional_text_is_rendered(self):
        asset = self.asset()
        plan = self.plan(asset, text=True).model_copy(update={"width": 108, "height": 192})
        result = render_plan(plan, {asset.id: asset}, self.directory / "text-render")
        self.assertEqual(result["qc"]["frame_count"], 30)
        self.assertTrue(Path(result["output_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
