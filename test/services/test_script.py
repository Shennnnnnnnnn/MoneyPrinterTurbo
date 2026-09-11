import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from app.services import script


class TestScriptParagraphs(unittest.TestCase):
    def test_preserves_manual_blank_line_boundaries(self):
        text = "One. Two.\n\nThree. Four. Five. Six. Seven. Eight."

        self.assertEqual(
            script.split_script_paragraphs(text),
            ["One. Two.", "Three. Four. Five. Six. Seven. Eight."],
        )

    def test_auto_groups_unformatted_script_into_three_to_five_sentences(self):
        text = " ".join(f"Sentence {index}." for index in range(1, 12))

        paragraphs = script.split_script_paragraphs(text)

        self.assertEqual([script.count_sentences(item) for item in paragraphs], [4, 4, 3])
        self.assertEqual(" ".join(paragraphs), text)

    def test_decimal_point_does_not_split_a_sentence(self):
        sentences = script.split_sentences(
            "The fee is 2.5 percent. This is the second sentence."
        )

        self.assertEqual(len(sentences), 2)
        self.assertEqual(sentences[0], "The fee is 2.5 percent.")

    def test_commas_and_semicolons_define_spoken_sentence_boundaries(self):
        sentences = script.split_sentences(
            "先介绍主题，再补充背景；最后给出结论。Then pause, then continue; finish."
        )

        self.assertEqual(
            sentences,
            [
                "先介绍主题，",
                "再补充背景；",
                "最后给出结论。",
                "Then pause,",
                "then continue;",
                "finish.",
            ],
        )


class TestScriptTimeline(unittest.TestCase):
    @staticmethod
    def _cue(start, end, content):
        return SimpleNamespace(
            start=timedelta(seconds=start),
            end=timedelta(seconds=end),
            content=content,
        )

    def test_uses_next_paragraph_start_as_visual_boundary(self):
        paragraphs = ["Alpha. Beta. Gamma.", "Delta. Epsilon. Zeta."]
        sub_maker = SimpleNamespace(
            cues=[
                self._cue(0.2, 0.8, "Alpha."),
                self._cue(0.9, 1.5, "Beta."),
                self._cue(1.6, 2.2, "Gamma."),
                self._cue(2.8, 3.4, "Delta."),
                self._cue(3.5, 4.1, "Epsilon."),
                self._cue(4.2, 4.8, "Zeta."),
            ]
        )

        timeline = script.build_script_timeline(
            paragraphs,
            audio_duration=5.0,
            sub_maker=sub_maker,
        )

        self.assertEqual(len(timeline), 2)
        self.assertAlmostEqual(timeline[0].start, 0.0)
        self.assertAlmostEqual(timeline[0].end, 2.8)
        self.assertAlmostEqual(timeline[1].start, 2.8)
        self.assertAlmostEqual(timeline[1].end, 5.0)

    def test_uses_subtitle_timing_when_submaker_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle_path = Path(temp_dir) / "subtitle.srt"
            subtitle_path.write_text(
                "1\n00:00:00,100 --> 00:00:01,000\nAlpha.\n\n"
                "2\n00:00:01,100 --> 00:00:02,000\nBeta.\n\n"
                "3\n00:00:02,500 --> 00:00:03,500\nGamma.\n\n",
                encoding="utf-8",
            )

            timeline = script.build_script_timeline(
                ["Alpha. Beta.", "Gamma."],
                audio_duration=4.0,
                subtitle_path=str(subtitle_path),
            )

        self.assertEqual(len(timeline), 2)
        self.assertAlmostEqual(timeline[0].end, 2.5)
        self.assertAlmostEqual(timeline[1].duration, 1.5)

    def test_falls_back_to_continuous_weighted_timing(self):
        timeline = script.build_script_timeline(
            ["Short.", "This paragraph contains several more spoken words."],
            audio_duration=9.0,
        )

        self.assertEqual(len(timeline), 2)
        self.assertAlmostEqual(sum(item.duration for item in timeline), 9.0)
        self.assertGreater(timeline[1].duration, timeline[0].duration)


if __name__ == "__main__":
    unittest.main()
