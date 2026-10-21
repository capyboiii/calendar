import calendar
import io
import unittest
import zipfile
from unittest import mock
from PIL import Image
from calforge.clone import prompts, session


class GridRepairTest(unittest.TestCase):
    def test_all_months_have_exact_sunday_first_table(self):
        for year in (2027, 2028):
            for month in range(1, 13):
                text = prompts.grid_redo(year, month, 'wrong column', layout_ref=True, attempt=2)
                self.assertIn('Image 2 is the target artwork', text)
                self.assertIn('never its dates', text)
                self.assertIn('Previous repair failed', text)
                for week in calendar.Calendar(6).monthdayscalendar(year, month):
                    self.assertIn(' | '.join(str(d) if d else 'BLANK' for d in week), text)

    def test_no_layout_reference_uses_image_one(self):
        text = prompts.grid_redo(2027, 3, 'wrong column')
        self.assertIn('Image 1 is the target artwork', text)
        self.assertNotIn('Image 2', text)
        self.assertNotIn('Previous repair failed', text)

    def test_download_zip_reads_images_without_extracting_paths(self):
        data = io.BytesIO()
        Image.new('RGB', (800, 600), 'red').save(data, format='PNG')
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../../page.png', data.getvalue())
            z.writestr('duplicate.png', data.getvalue())
            z.writestr('bad.png', b'broken')
            z.writestr('note.txt', b'not an image')
        s = object.__new__(session.Session)
        with mock.patch.object(s, 'download_files', return_value=[('pages.zip', archive.getvalue())]):
            self.assertEqual(s.file_images(10), [data.getvalue()])

    def test_download_promise_without_files_is_not_success(self):
        s = object.__new__(session.Session)
        with mock.patch.object(s, 'download_files', return_value=[]):
            self.assertEqual(s.file_images(10), [])

    def test_collector_checks_actual_files_before_no_image_error(self):
        from tests.test_clone import CollectTest, state
        for images in ([b'validated image'], []):
            with self.subTest(files=bool(images)):
                case = CollectTest()
                with mock.patch.object(session.Session, 'file_images', return_value=images) as download:
                    turn = case.collect(lambda t: state(tail='Download 10 Calendar Grid Pages'), 10)
                download.assert_called_once_with(10)
                self.assertEqual(turn.images, images)
                if images:
                    self.assertIsNone(turn.problem)
                else:
                    self.assertIsInstance(turn.problem, session.TempError)

    def test_failed_repairs_resume_one_month_with_attachments(self):
        from tests.test_clone import BookGridTest, FakeSession
        from calforge.clone import run, store
        case = BookGridTest()
        case.setUp()
        try:
            initial = case.grid_pages(range(1, 9))
            s = FakeSession([session.Turn(initial)] + [session.Turn() for _ in range(4)])
            with mock.patch('calforge.imagegen.generate.accept_grid_page', case.accept):
                with self.assertRaisesRegex(run.TempError, 'mở phiên mới'):
                    case.b.grid_work(s, 'acc1')
            self.assertIn('9', store.read(case.b.d)['grid_repairs'])
            s2 = FakeSession([session.Turn(case.grid_pages([9], 70)),
                              session.Turn(case.grid_pages([10], 80)),
                              session.Turn(case.grid_pages([11, 12], 90))])
            with mock.patch('calforge.imagegen.generate.accept_grid_page', case.accept):
                case.b.grid_work(s2, 'acc2')
            self.assertEqual(s2.sent[0][1], 1)
            self.assertEqual([p.name for p in s2.sent[0][2]], ['g01.png', 'm09.png'])
            self.assertEqual(s2.sent[1][1], 1)
            self.assertEqual(case.b.missing('g'), [])
            self.assertFalse(store.read(case.b.d)['grid_repairs'])
        finally:
            case.doCleanups()


if __name__ == '__main__':
    unittest.main()
