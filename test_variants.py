import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import io
import tempfile
import shutil

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import config
from pipeline.hook import validate_hook
from pipeline.editor import _resolve_font_path
from pipeline.karaoke import create_karaoke_concat


class TestHookValidation(unittest.TestCase):
    """
    Test cases for validate_hook() validation bounds, word count limits,
    description-only patterns, and contrast/uncertainty markers.
    """

    def test_word_count_lower_bound_fail(self):
        # 3 words should fail (limit is 4 to 16)
        hook = "actually broke never"
        self.assertFalse(validate_hook(hook))

    def test_word_count_lower_bound_pass(self):
        # 4 words should pass
        hook = "actually broke never still"
        self.assertTrue(validate_hook(hook))

    def test_word_count_upper_bound_pass(self):
        # 16 words should pass
        hook = "actually broke never still survivors nobody would've should've does doesn't somehow barely no way check this"
        words = hook.split()
        self.assertEqual(len(words), 16)
        self.assertTrue(validate_hook(hook))

    def test_word_count_upper_bound_fail(self):
        # 17 words should fail
        hook = "actually broke never still survivors nobody would've should've does doesn't somehow barely no way check this extra"
        words = hook.split()
        self.assertEqual(len(words), 17)
        self.assertFalse(validate_hook(hook))

    def test_question_mark_fail(self):
        # Hooks ending with a question mark must fail validation
        hook = "would've survived this stunt?"
        self.assertFalse(validate_hook(hook))

    def test_description_only_patterns(self):
        # Description-only patterns should fail validation
        # Pattern 1: ^(off|on|at|in|from|near) (the|a)
        self.assertFalse(validate_hook("off the helicopter stunt"))
        # Pattern 2: ^(this is|that was) (a |an )?(crazy|cool|wild|insane)
        self.assertFalse(validate_hook("this is a crazy physics glitch"))
        # Pattern 3: ^(watch this|check this|look at this)$
        self.assertFalse(validate_hook("watch this"))
        # Pattern 4: ^[A-Za-z-]+ (just )?(went|goes|jumps|launches|drives|flies|falls)
        self.assertFalse(validate_hook("player just jumps into the void"))

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_contrast_marker_warning_trigger(self, mock_stdout):
        # A valid hook (4-16 words, no question mark) but with no contrast markers
        # should log a warning but still return True.
        hook = "jumping into the swimming pool"
        res = validate_hook(hook)
        self.assertTrue(res)
        self.assertIn("WARNING: likely-descriptive", mock_stdout.getvalue())

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_new_contrast_markers(self, mock_stdout):
        # Test new contrast markers: "would've", "should've", "does", "doesn't"
        # None of these should trigger the descriptive warning.
        markers = ["would've", "should've", "does", "doesn't"]
        for marker in markers:
            # Construct a simple hook containing the marker (at least 4 words)
            hook = f"he {marker} crash here"
            mock_stdout.seek(0)
            mock_stdout.truncate(0)
            
            res = validate_hook(hook)
            self.assertTrue(res)
            # Verify no warning about missing contrast markers is printed
            self.assertNotIn("WARNING: likely-descriptive", mock_stdout.getvalue())


class TestResolveFontPath(unittest.TestCase):
    """
    Test cases for _resolve_font_path() behavior under different caption_font_style settings.
    """

    def setUp(self):
        self.original_clip = config.CLIP.copy()

    def tearDown(self):
        config.CLIP = self.original_clip

    @patch('os.path.exists')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_font_style_current(self, mock_stdout, mock_exists):
        config.CLIP["caption_font_style"] = "current"
        config.CLIP["font_path"] = "assets/Oswald-Bold.ttf"
        
        path = _resolve_font_path()
        self.assertEqual(path, "assets/Oswald-Bold.ttf")
        self.assertNotIn("WARNING", mock_stdout.getvalue())

    @patch('os.path.exists')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_font_style_gta_missing_path(self, mock_stdout, mock_exists):
        config.CLIP["caption_font_style"] = "gta_style"
        config.CLIP["caption_font_path_gta_style"] = ""
        config.CLIP["font_path"] = "assets/Oswald-Bold.ttf"
        mock_exists.return_value = False
        
        path = _resolve_font_path()
        self.assertEqual(path, "assets/Oswald-Bold.ttf")
        self.assertIn("WARNING: caption_font_style is 'gta_style' but caption_font_path_gta_style is empty or does not exist", mock_stdout.getvalue())

    @patch('os.path.exists')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_font_style_gta_nonexistent_path(self, mock_stdout, mock_exists):
        config.CLIP["caption_font_style"] = "gta_style"
        config.CLIP["caption_font_path_gta_style"] = "assets/nonexistent_gta_font.ttf"
        config.CLIP["font_path"] = "assets/Oswald-Bold.ttf"
        mock_exists.side_effect = lambda p: p != "assets/nonexistent_gta_font.ttf"
        
        path = _resolve_font_path()
        self.assertEqual(path, "assets/Oswald-Bold.ttf")
        self.assertIn("WARNING: caption_font_style is 'gta_style' but caption_font_path_gta_style is empty or does not exist", mock_stdout.getvalue())

    @patch('os.path.exists')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_font_style_gta_existing_path(self, mock_stdout, mock_exists):
        config.CLIP["caption_font_style"] = "gta_style"
        config.CLIP["caption_font_path_gta_style"] = "assets/Pricedown.ttf"
        config.CLIP["font_path"] = "assets/Oswald-Bold.ttf"
        mock_exists.side_effect = lambda p: p == "assets/Pricedown.ttf"
        
        path = _resolve_font_path()
        self.assertEqual(path, "assets/Pricedown.ttf")
        self.assertNotIn("WARNING", mock_stdout.getvalue())


class TestCreateKaraokeConcat(unittest.TestCase):
    """
    Test cases for create_karaoke_concat() color cycling behavior, emphasis color
    reservation, and output concat file verification.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.font_path = "assets/Oswald-Bold.ttf"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    @patch('PIL.ImageDraw.ImageDraw.text')
    def test_color_cycling_and_emphasis(self, mock_text):
        word_timings = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "beautiful", "start": 0.5, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 1.8}
        ]
        emphasis_word = "world"
        fontsize = 60
        video_duration = 2.0
        cycle_colors = ["#00FFFF", "#FFFF00", "#FF8C00"]

        # Run with color cycling enabled
        concat_file = create_karaoke_concat(
            word_timings=word_timings,
            emphasis_word=emphasis_word,
            font_path=self.font_path,
            fontsize=fontsize,
            tmp_dir=self.tmp_dir,
            video_duration=video_duration,
            cycle_enabled=True,
            cycle_colors=cycle_colors
        )

        # 1. Verify concat file formats and contents
        self.assertTrue(os.path.exists(concat_file))
        with open(concat_file, "r") as f:
            content = f.read()
        
        # Concat file should reference generated state PNG files and durations
        # Word timings total states: active_idx goes from -1 to 2
        for active_idx in range(-1, 3):
            expected_png = f"state_{active_idx}.png"
            self.assertTrue(os.path.exists(os.path.join(self.tmp_dir, expected_png)))
            self.assertIn(f"file '{os.path.join(self.tmp_dir, expected_png)}'", content)

        # Check line patterns in concat file:
        # e.g., duration 0.500 or duration 0.800
        self.assertIn("duration 0.500", content)
        self.assertIn("duration 0.800", content)

        # 2. Verify active word coloring and emphasis reservation
        # We parse the fill calls made to Pillow's text drawing API.
        # Format of fill_calls is (word_text, fill_color)
        fill_calls = [
            (call[0][1], call[1]['fill'])
            for call in mock_text.call_args_list
            if call[1].get('fill') != 'black'
        ]

        # There are 4 states: active_idx = -1, 0, 1, 2. Each draws 3 words.
        # Total fill calls should be 4 * 3 = 12.
        self.assertEqual(len(fill_calls), 12)

        # State -1: no highlight (all white)
        state_neg1 = fill_calls[0:3]
        self.assertEqual(state_neg1[0], ("HELLO", "white"))
        self.assertEqual(state_neg1[1], ("BEAUTIFUL", "white"))
        self.assertEqual(state_neg1[2], ("WORLD", "white"))

        # State 0: word index 0 active ("HELLO")
        state_0 = fill_calls[3:6]
        # Active word index 0: should use cycle_colors[0] = "#00FFFF"
        self.assertEqual(state_0[0], ("HELLO", "#00FFFF"))
        self.assertEqual(state_0[1], ("BEAUTIFUL", "white"))
        self.assertEqual(state_0[2], ("WORLD", "white"))

        # State 1: word index 1 active ("BEAUTIFUL")
        state_1 = fill_calls[6:9]
        # Active word index 1: should use cycle_colors[1] = "#FFFF00"
        self.assertEqual(state_1[0], ("HELLO", "white"))
        self.assertEqual(state_1[1], ("BEAUTIFUL", "#FFFF00"))
        self.assertEqual(state_1[2], ("WORLD", "white"))

        # State 2: word index 2 active ("WORLD"), which matches emphasis word "world"
        state_2 = fill_calls[9:12]
        # Active word index 2: since it's the emphasis word, the cycle color must be
        # excluded/reserved and instead use emp_color = "#FF6B35"
        self.assertEqual(state_2[0], ("HELLO", "white"))
        self.assertEqual(state_2[1], ("BEAUTIFUL", "white"))
        self.assertEqual(state_2[2], ("WORLD", "#FF6B35"))


if __name__ == '__main__':
    unittest.main()
