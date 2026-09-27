import unittest
from unittest import mock

from calforge.imagegen.driver import classify, generating, wants_source
from calforge.publish import printify
from calforge.publish.listing import build_listing

from tests import fixtures


class PositionMappingTest(unittest.TestCase):
    def setUp(self):
        # không đọc/ghi file mapping thật khi test
        patcher = mock.patch.object(printify, "POSITIONS_FILE", mock.MagicMock(exists=lambda: False))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_named_positions(self):
        months = ["january", "february", "march", "april", "may", "june", "july", "august",
                  "september", "october", "november", "december"]
        positions = ["front_cover", "back_cover"] + [m for m in months] + [f"{m}_grid" for m in months]
        mapping = printify.map_positions(positions)
        self.assertEqual(mapping["front_cover"], "front_cover")
        self.assertEqual(mapping["march"], "m03_month")
        self.assertEqual(mapping["march_grid"], "m03_grid")
        self.assertEqual(len(set(mapping.values())), 26)

    def test_numbered_positions(self):
        positions = [f"page_{i}" for i in range(1, 27)]
        mapping = printify.map_positions(positions)
        self.assertEqual(mapping["page_1"], "front_cover")
        self.assertEqual(mapping["page_2"], "m01_month")
        self.assertEqual(mapping["page_3"], "m01_grid")
        self.assertEqual(mapping["page_26"], "back_cover")

    def test_unknown_positions_stop(self):
        with self.assertRaises(printify.PrintifyError):
            printify.map_positions(["left", "right", "middle"])


class ListingTest(unittest.TestCase):
    def test_listing_from_concept(self):
        c = fixtures.concept()
        c["year"] = 2027
        lst = build_listing(c)
        self.assertLessEqual(len(lst["title"]), 140)
        self.assertEqual(len(lst["tags"]), 13)
        self.assertIn("Mark 4:39", lst["description"])
        self.assertIn("Prayer List", lst["description"])


class ClassifyTest(unittest.TestCase):
    def test_messages(self):
        self.assertEqual(classify("You've hit your limit for image generation. Try again later"), "quota")
        self.assertEqual(classify("You're out of image generation messages for now. "
                                  "Please try again in 11 hours."), "quota")
        self.assertEqual(classify("I can't create that image because it violates our content policy"), "refused")
        self.assertEqual(classify("Something went wrong while generating"), "error")
        self.assertEqual(classify("Here is your image"), "")

    def test_edit_mode_replies_are_detected(self):
        # 2 câu trả lời thật: ChatGPT coi nhầm là việc sửa ảnh và đòi ảnh gốc
        self.assertTrue(wants_source("I couldn’t generate this image because the image tool incorrectly treated "
                                     "the request as an edit requiring a source image"))
        self.assertTrue(wants_source("Please upload the color-and-texture swatch image in this chat. I can’t "
                                     "access a usable attached image target"))
        self.assertFalse(wants_source("Creating image"))
        self.assertFalse(wants_source("Here is your calendar artwork."))

    def test_drawing_placeholders_count_as_generating(self):
        # Chữ tạm lúc ChatGPT đang vẽ: phải chờ tiếp, không được coi là "trả lời mà không có ảnh".
        for text in ("Creating image", "Getting started", "Adding details", "Almost done...", "Đang tạo hình ảnh"):
            self.assertTrue(generating({"tail": text}), text)
        self.assertTrue(generating({"tail": "", "pending": True}))  # khung chờ / ảnh chưa tải xong
        self.assertFalse(generating({"tail": "Would you like me to adjust the colors?"}))



class RotationTest(unittest.TestCase):
    def test_rotation_starts_after_last_used(self):
        import tempfile
        from pathlib import Path

        from calforge.llm.chatgpt_web import ChatGPTWebBackend

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n in ("acc1", "acc2", "acc3"):
                (root / "profiles" / n).mkdir(parents=True)
            b = ChatGPTWebBackend(str(root / "profiles"), None, state_file=root / "rot.json")
            self.assertEqual(b.rotation_order(), ["acc2", "acc3", "acc1"])  # acc1 để cuối
            b.mark_used("acc2")
            self.assertEqual(b.rotation_order(), ["acc3", "acc1", "acc2"])
            b.mark_used("acc3")
            self.assertEqual(b.rotation_order()[0], "acc1")


if __name__ == "__main__":
    unittest.main()
