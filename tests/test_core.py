import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ehky import compose, fonts, project, subs, text, tts
from ehky.cli import run
from ehky.tts import Word


def quiet(argv):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return run(argv)


class TextTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(text.normalize("  مرحبا \n\n  بالعالم\u200b  "), "مرحبا بالعالم")

    def test_validate_rejects_empty_and_too_long(self):
        with self.assertRaises(ValueError):
            text.validate("  ")
        with self.assertRaises(ValueError):
            text.validate("ا" * (text.MAX_SCRIPT_CHARS + 1))

    def test_split_sentences_arabic_question_mark(self):
        self.assertEqual(text.split_sentences("إزيك؟ تمام. الحمد لله"), ["إزيك؟", "تمام.", "الحمد لله"])

    def test_split_lines_keeps_writer_lines_together(self):
        script = "بنيتها. وراجعت الكود.\n\nوصلّحت الـ subtitles.\n"
        self.assertEqual(text.split_lines(script), ["بنيتها. وراجعت الكود.", "وصلّحت الـ subtitles."])

    def test_split_lines_breaks_very_long_lines_at_sentence_ends(self):
        line = " ".join(["جملة طويلة شوية."] * 30)
        chunks = text.split_lines(line, max_chars=60)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 60 for c in chunks))
        self.assertEqual(" ".join(chunks), text.normalize(line))


class TtsTests(unittest.TestCase):
    def test_validators(self):
        self.assertEqual(tts.validate_voice("ar-EG-SalmaNeural"), "ar-EG-SalmaNeural")
        self.assertEqual(tts.validate_speaker("Tareq"), "Tareq")
        self.assertEqual(tts.validate_rate("-10%"), "-10%")
        for bad in ["", "salma", "ar-EG-Salma; rm -rf /", "../x"]:
            with self.assertRaises(ValueError):
                tts.validate_voice(bad)
        for bad in ["", "Tareq; ls", "x" * 30]:
            with self.assertRaises(ValueError):
                tts.validate_speaker(bad)
        with self.assertRaises(ValueError):
            tts.validate_rate("fast")

    def test_estimate_words_covers_span_in_order(self):
        words = tts.estimate_words("واحد اتنين تلاتة", 1.0, 4.0)
        self.assertEqual([w.text for w in words], ["واحد", "اتنين", "تلاتة"])
        self.assertAlmostEqual(words[0].start, 1.0)
        self.assertAlmostEqual(words[-1].end, 4.0)
        for a, b in zip(words, words[1:], strict=False):
            self.assertAlmostEqual(a.end, b.start)

    def test_auto_engine_falls_back_to_edge(self):
        with mock.patch.object(tts, "voicetut_available", return_value=False):
            self.assertEqual(tts.resolve_engine("auto"), "edge")
            with self.assertRaises(RuntimeError):
                tts.resolve_engine("voicetut")
        with mock.patch.object(tts, "voicetut_available", return_value=True):
            self.assertEqual(tts.resolve_engine("auto"), "voicetut")

    def test_edge_retries_then_fails_cleanly(self):
        with (
            mock.patch.object(tts, "_network_settings", return_value=None),
            mock.patch.object(tts, "_edge_once", side_effect=OSError("boom")) as once,
            mock.patch.object(tts.time, "sleep"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            with self.assertRaises(RuntimeError):
                tts.synthesize_edge("مرحبا", tts.DEFAULT_VOICE, Path(tmp) / "a.mp3", attempts=3)
            self.assertEqual(once.call_count, 3)

    def test_recording_timing_spans_whole_audio(self):
        n = tts.from_recording(["جملة قصيرة.", "وجملة تانية أطول شوية."], 10.0)
        self.assertAlmostEqual(n.words[0].start, 0.0)
        self.assertAlmostEqual(n.words[-1].end, 10.0)
        self.assertFalse(n.exact)


class SubsTests(unittest.TestCase):
    def words(self, items):
        return [Word(t, s, e) for t, s, e in items]

    def test_lines_break_on_sentence_end_and_pause(self):
        w = self.words([("أهلا.", 0, 0.5), ("ازيك", 0.6, 1.0), ("عامل", 2.0, 2.4), ("ايه", 2.4, 2.8)])
        lines = subs.group_lines(w)
        self.assertEqual([line.text for line in lines], ["أهلا.", "ازيك", "عامل ايه"])

    def test_lines_respect_max_chars(self):
        w = self.words([("كلمة", i * 0.3, i * 0.3 + 0.3) for i in range(20)])
        self.assertTrue(all(len(line.text) <= 32 for line in subs.group_lines(w)))

    def test_highlight_one_event_per_word_and_no_gaps(self):
        w = self.words([("عملت", 0.1, 0.5), ("أداة", 0.5, 1.0)])
        ev = subs.events(subs.group_lines(w))
        self.assertEqual(len(ev), 2)
        self.assertAlmostEqual(ev[0][1], ev[1][0])
        self.assertIn(subs.HIGHLIGHT, ev[0][2])

    def test_ass_header_and_escaping(self):
        ass = subs.build_ass(self.words([("a{b}", 0, 1.5)]), 1080, 1920, "Cairo", 70, highlight=False)
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("Style: Default,Cairo,70", ass)
        self.assertIn(",-1\n", ass)  # auto base direction, keeps RTL order with highlights
        self.assertIn("a(b)", ass)
        self.assertNotIn("{b}", ass)


class ComposeTests(unittest.TestCase):
    def test_segments_add_up_after_crossfades(self):
        per = compose.segment_length(10.0, 3)
        self.assertAlmostEqual(3 * per - 2 * compose.FADE, 10.0)

    def test_media_args(self):
        argv = compose.build_ffmpeg_args(
            [Path("a.png"), Path("b.mp4")], Path("v.mp3"), Path("s.ass"), Path("o.mp4"), 10.0, "9:16"
        )
        joined = " ".join(argv)
        self.assertIn("-loop 1", joined)
        self.assertIn("-stream_loop -1", joined)
        self.assertIn("xfade=transition=fade", joined)
        self.assertIn("[2:a]aresample=48000", joined)
        self.assertTrue(joined.endswith("o.mp4"))

    def test_single_media_and_no_subtitles(self):
        argv = compose.build_ffmpeg_args([Path("a.jpg")], Path("v.mp3"), None, Path("o.mp4"), 4.0, "1:1")
        joined = " ".join(argv)
        self.assertNotIn("xfade", joined)
        self.assertNotIn("ass=", joined)

    def test_theme_background(self):
        argv = compose.build_ffmpeg_args(
            [], Path("v.mp3"), Path("s.ass"), Path("o.mp4"), 4.0, "16:9", "sand", Path("/f")
        )
        joined = " ".join(argv)
        self.assertIn("s=1920x1080:c0=0xf3ece0", joined)
        self.assertIn("ass=filename='s.ass':fontsdir='/f'", joined)
        self.assertIn("[1:a]aresample=48000", joined)

    def test_music_is_looped_and_ducked_under_the_voice(self):
        argv = compose.build_ffmpeg_args(
            [], Path("v.mp3"), None, Path("o.mp4"), 8.0, "9:16", music=Path("m.mp3"), music_volume=0.4
        )
        joined = " ".join(argv)
        self.assertIn("-i v.mp3 -stream_loop -1 -i m.mp3", joined)
        self.assertIn("[2:a]aresample=48000,volume=0.40", joined)
        self.assertIn("[bgm][key]sidechaincompress", joined)
        self.assertIn("-map [aout]", joined)

    def test_no_music_means_voice_only(self):
        argv = compose.build_ffmpeg_args([], Path("v.mp3"), None, Path("o.mp4"), 8.0, "9:16")
        self.assertNotIn("sidechaincompress", " ".join(argv))

    def test_windows_path_escaping(self):
        self.assertEqual(compose._esc_filter_path(Path("C:/x/it's.ass")), "C\\:/x/it\\'s.ass")

    def test_find_media_sorted_and_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ["b.jpg", "a.png", "README.txt"]:
                (Path(tmp) / name).write_bytes(b"x")
            self.assertEqual([p.name for p in compose.find_media(Path(tmp))], ["a.png", "b.jpg"])


class FontTests(unittest.TestCase):
    def test_none_when_no_fonts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(fonts.find_arabic_font([Path(tmp)]))

    def test_prefers_better_arabic_font(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "DejaVuSans.ttf").write_bytes(b"x")
            (Path(tmp) / "Cairo-Regular.ttf").write_bytes(b"x")
            self.assertEqual(fonts.find_arabic_font([Path(tmp)]), ("Cairo", Path(tmp)))


class ProjectTests(unittest.TestCase):
    def test_every_template_creates_a_valid_project(self):
        for name in project.TEMPLATES:
            with tempfile.TemporaryDirectory() as tmp:
                folder = project.create(Path(tmp) / "p", name)
                settings = project.load_settings(folder)
                self.assertEqual(settings["aspect"], project.TEMPLATES[name]["settings"]["aspect"])
                text.validate((folder / "script.txt").read_text(encoding="utf-8"))

    def test_refuses_non_empty_folder_and_bad_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text("x")
            with self.assertRaises(ValueError):
                project.create(Path(tmp), "fact")
            with self.assertRaises(ValueError):
                project.create(Path(tmp) / "new", "nope")

    def test_settings_reject_unknown_key_and_wrong_type(self):
        for content in ['aspct = "9:16"', "subtitles = 1", "music_volume = true", "not toml ["]:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "ehky.toml").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    project.load_settings(Path(tmp))


class CliTests(unittest.TestCase):
    def script(self, tmp, content="مرحبا بالعالم."):
        path = Path(tmp) / "s.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_init_then_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = str(Path(tmp) / "vid")
            self.assertEqual(quiet(["init", folder, "--template", "tutorial"]), 0)
            self.assertEqual(quiet(["make", folder, "--dry-run", "--no-subtitles"]), 0)
            self.assertEqual(quiet([folder, "--dry-run", "--no-subtitles"]), 0)  # shorthand
            self.assertFalse((Path(folder) / "video.mp4").exists())

    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.mp4"
            out.write_bytes(b"x")
            self.assertEqual(quiet(["make", self.script(tmp), "-o", str(out)]), 2)

    def test_bad_inputs_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.script(tmp)
            for extra in (
                ["--voice", "bad"],
                ["--speaker", "a b"],
                ["--rate", "x"],
                ["-o", "x.avi"],
                ["--font-size", "5"],
                ["--media", str(Path(tmp) / "nope")],
            ):
                self.assertEqual(quiet(["make", s, "--dry-run", *extra]), 2, extra)
            self.assertEqual(quiet(["make", "missing.txt"]), 2)
            self.assertEqual(quiet(["make", self.script(tmp, "   ")]), 2)

    def test_audio_must_exist_and_be_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.script(tmp)
            self.assertEqual(quiet(["make", s, "--dry-run", "--audio", str(Path(tmp) / "no.wav")]), 2)
            self.assertEqual(quiet(["make", s, "--dry-run", "--audio", s]), 2)  # .txt is not audio

    def test_subtitles_refused_cleanly_without_libass(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("ehky.compose.has_libass", return_value=False):
            self.assertEqual(quiet(["make", self.script(tmp), "--dry-run", "--subtitles"]), 2)
            self.assertEqual(quiet(["make", self.script(tmp), "--dry-run", "--no-subtitles"]), 0)

    def test_music_must_be_audio_and_volume_in_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.script(tmp)
            self.assertEqual(quiet(["make", s, "--dry-run", "--music", s]), 2)
            self.assertEqual(quiet(["make", s, "--dry-run", "--music", str(Path(tmp) / "no.mp3")]), 2)
            self.assertEqual(quiet(["make", s, "--dry-run", "--music-volume", "1.5"]), 2)

    def test_project_music_setting_is_resolved_relative_to_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "p"
            project.create(folder, "fact")
            (folder / "song.mp3").write_bytes(b"x")
            toml = folder / "ehky.toml"
            toml.write_text(toml.read_text(encoding="utf-8").replace('music = ""', 'music = "song.mp3"'), "utf-8")
            self.assertEqual(quiet(["make", str(folder), "--dry-run", "--no-subtitles"]), 0)
            (folder / "song.mp3").unlink()
            self.assertEqual(quiet(["make", str(folder), "--dry-run", "--no-subtitles"]), 2)

    def test_voices(self):
        self.assertEqual(quiet(["voices"]), 0)


if __name__ == "__main__":
    unittest.main()
