import tempfile
import unittest
from pathlib import Path
from unittest import mock
from calforge import layout
from calforge.publish import listing, r2
from tests.test_r2_parallel import CFG


class DesignUrlsTest(unittest.TestCase):
    def test_push_and_rewrite_never_add_design_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp)
            layout.ensure_system(book)
            f = book / 'listing.txt'
            original = 'TITLE\nTên cuốn\n\nDESCRIPTION\nMô tả giữ nguyên\n'
            f.write_text(original, encoding='utf-8-sig')
            pages = {}
            for fid in r2.SIZES:
                folder = layout.print_dir(book, fid)
                folder.mkdir(parents=True, exist_ok=True)
                for name in r2.PAGE_ORDER:
                    p = folder / (name + '.png')
                    p.write_bytes(b'image')
                    pages[f'{layout.SIZE_LABEL[fid]}/{p.name}'] = p
            with mock.patch.object(r2, 'book_files', return_value=pages):
                s3 = mock.Mock()
                r2.push_book(book, CFG, lambda _:None, s3=s3)
                first = f.read_text(encoding='utf-8-sig')
                self.assertTrue(first.startswith(original.rstrip()))
                urls = [line for line in first.splitlines() if line.startswith('https://')]
                self.assertEqual(urls, [])
                self.assertNotIn('DESIGN URLS', first)
                r2.push_book(book, CFG, lambda _:None, s3=s3)
                self.assertEqual(f.read_text(encoding='utf-8-sig'), first)
                listing.write_listing_txt(book, {'title':'New title', 'tags':[], 'description_text':'New description'})
                self.assertEqual(f.read_text(encoding='utf-8-sig').count('https://'), 0)

    def test_legacy_cleanup_is_idempotent_and_retains_description(self):
        old='SKU\nWCB-TST-ABCDE\nWCB-TST-ABCDE-11PD  (11 x 8.5 Printable)\nWCB-TST-ABCDE-11SM  (11 x 8.5 Spiral Matte)\n\nTITLE\nTitle\n\nDESCRIPTION\nPrintable mention in prose stays.\n\nDESIGN URLS\n11x8.5\nhttps://example/design.png\n'
        clean=listing.clean_listing_text(old)
        self.assertNotIn('-11PD',clean)
        self.assertNotIn('DESIGN URLS',clean)
        self.assertIn('-11SM',clean)
        self.assertIn('(11 x 8.5 Matte)',clean)
        self.assertNotIn('Spiral',clean)
        self.assertIn('Printable mention in prose stays.',clean)
        self.assertEqual(clean.count('- Paper: Matte or Glossy'),1)
        self.assertEqual(listing.clean_listing_text(clean),clean)

    def test_failed_upload_does_not_change_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp)
            layout.ensure_system(book)
            f = book / 'listing.txt'
            f.write_text('original', encoding='utf-8-sig')
            page = book / 'page.png'
            page.write_bytes(b'image')
            s3 = mock.Mock()
            s3.upload_file.side_effect = RuntimeError('network')
            cfg = {'r2':dict(CFG['r2'], upload_retries=1)}
            with mock.patch.object(r2, 'book_files', return_value={'11x8.5/page.png':page}):
                with self.assertRaises(r2.R2Error):
                    r2.push_book(book, cfg, lambda _:None, s3=s3, sleep=lambda _:None)
            self.assertEqual(f.read_text(encoding='utf-8-sig'), 'original')
