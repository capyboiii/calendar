import copy
import json
import tempfile
import unittest
from pathlib import Path
from calforge import layout
from calforge.clone import run, prompts
from tests.test_clone import META

class CaptionTest(unittest.TestCase):
    def test_objects_normalize_and_invalid_values_fail_validation(self):
        meta = copy.deepcopy(META)
        meta['months'] = [{'month': m, 'caption': f'Caption {i}'} for i, m in enumerate(prompts.MONTHS)]
        self.assertEqual(run.month_captions(meta['months']), [f'Caption {i}' for i in range(12)])
        self.assertFalse(run.validate_meta(meta))
        for value in (None, 3, [], {}, {'caption': {}}, {'caption': ' '}, {'month': 'December', 'caption': 'Hi'}):
            bad = copy.deepcopy(meta)
            bad['months'][0] = value
            self.assertTrue(run.validate_meta(bad), value)
        with self.assertRaises(ValueError):
            run.month_captions(['caption'] * 13)

    def test_saved_book_repair_preserves_other_fields_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp)
            layout.tech(book).mkdir(parents=True)
            meta = {'months': [{'month': i, 'caption': f'Caption {i}'} for i in range(1, 13)]}
            (layout.tech(book) / 'clone_meta.json').write_text(json.dumps(meta))
            path = layout.concept_file(book)
            original = {'source': 'clone', 'title': 'Keep me', 'months': [
                {'month': i, 'subtitle': str(meta['months'][i-1]), 'content': {}} for i in range(1, 13)]}
            path.write_text(json.dumps(original))
            run.repair_month_captions(book)
            result = json.loads(path.read_text())
            self.assertEqual(result['title'], 'Keep me')
            self.assertEqual(result['months'][0]['subtitle'], 'Caption 1')
            before = path.stat().st_mtime_ns
            run.repair_month_captions(book)
            self.assertEqual(before, path.stat().st_mtime_ns)
            self.assertEqual(json.loads(path.with_name('concept_before_caption_fix.json').read_text()), original)
