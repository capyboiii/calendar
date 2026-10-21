import base64,csv,io,unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from calforge.publish.selected_sheet_xlsx import export_selected_xlsx,NS,workbook_bytes
from tests.test_selected_sheet_csv import catalog

class SelectedXlsxTest(unittest.TestCase):
    def test_xlsx_has_exact_values_styles_filters_freeze_and_bounded_width(self):
        text,original=catalog()
        result=export_selected_xlsx('WCB-AA-12345',sheet_csv=text)
        self.assertTrue(result['filename'].endswith('.xlsx'))
        self.assertNotIn('csv',result)
        with ZipFile(io.BytesIO(base64.b64decode(result['xlsx_base64']))) as z:
            self.assertIsNone(z.testzip())
            for name in z.namelist():ET.fromstring(z.read(name))
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));ns={'s':NS}
            rows=[[c.find('s:is/s:t',ns).text or '' for c in r.findall('s:c',ns)]
                  for r in sheet.findall('s:sheetData/s:row',ns)]
            self.assertEqual(rows,[original[0],*original[1:6]])
            self.assertEqual(sheet.find('s:autoFilter',ns).attrib['ref'],'A1:H6')
            self.assertEqual(sheet.find('s:sheetViews/s:sheetView/s:pane',ns).attrib['state'],'frozen')
            self.assertTrue(all(float(c.attrib['width'])<=65 for c in sheet.findall('s:cols/s:col',ns)))
            style=ET.fromstring(z.read('xl/styles.xml'))
            self.assertTrue(all(a.attrib.get('wrapText')=='1' for a in style.findall('s:cellXfs/s:xf/s:alignment',ns)))

    def test_literal_formulas_and_unicode_are_preserved_as_text(self):
        rows=[['SKU','Title'],['WCB-AA-12345','=HYPERLINK("bad") & tiếng Việt\nNext line']]
        with ZipFile(io.BytesIO(workbook_bytes(rows))) as z:
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));ns={'s':NS}
            self.assertEqual(sheet.findall('.//s:f',ns),[])
            cells=sheet.findall('.//s:t',ns)
            self.assertEqual(cells[-1].text,rows[-1][-1])

if __name__=='__main__':unittest.main()
