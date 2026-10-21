"""Formatted, dependency-free XLSX export for the TXT SKU picker."""
from __future__ import annotations

import base64
import csv
import io
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .selected_sheet_csv import export_selected

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def _text(value):
    # XML 1.0 disallows these control characters; retain tabs/newlines and all
    # normal Unicode. inlineStr also keeps leading '=' as text, never a formula.
    return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value))


def _column(index):
    name = ''
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def workbook_bytes(rows):
    header = rows[0]
    widths = {'SKU': 27, 'Description': 55, 'Tags': 32, 'Title': 45,
              'Sizes': 18, 'Paper': 14, 'Design': 65, 'Mockup': 60}
    cols = ''.join(f'<col min="{i}" max="{i}" width="{widths.get(h, 28)}" customWidth="1"/>'
                   for i, h in enumerate(header, 1))
    title = header.index('Title')
    xml_rows = []
    for index, row in enumerate(rows, 1):
        base = index > 1 and bool(row[title].strip())
        height = 30 if index == 1 else 150 if base else 105
        cells = []
        for col, value in enumerate(row, 1):
            style = 1 if index == 1 else 2 if base else 0
            cells.append(f'<c r="{_column(col)}{index}" s="{style}" t="inlineStr">'
                         f'<is><t xml:space="preserve">{_text(value)}</t></is></c>')
        xml_rows.append(f'<row r="{index}" ht="{height}" customHeight="1">{"".join(cells)}</row>')
    last = f'{_column(len(header))}{len(rows)}'
    worksheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{NS}"><dimension ref="A1:{last}"/>
<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"/><selection pane="bottomRight" activeCell="B2" sqref="B2"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="18"/><cols>{cols}</cols><sheetData>{''.join(xml_rows)}</sheetData>
<autoFilter ref="A1:{last}"/><pageMargins left="0.25" right="0.25" top="0.4" bottom="0.4" header="0.2" footer="0.2"/>
</worksheet>'''
    styles = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="10"/><color rgb="FF263C35"/><name val="Calibri"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF315C50"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEEF4EF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom style="hair"><color rgb="FFE0E5DF"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1" applyNumberFormat="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1" applyFill="1" applyFont="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="49" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1" applyFill="1" applyNumberFormat="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    files = {
        '[Content_Types].xml': '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''',
        '_rels/.rels': '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''',
        'xl/workbook.xml': f'''<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sản phẩm đã chọn" sheetId="1" r:id="rId1"/></sheets></workbook>''',
        'xl/_rels/workbook.xml.rels': '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''',
        'xl/worksheets/sheet1.xml': worksheet,
        'xl/styles.xml': styles,
    }
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data.encode('utf-8'))
    return output.getvalue()


def export_selected_xlsx(text, *, sheet_csv=None):
    result = export_selected(text, sheet_csv=sheet_csv)
    rows = list(csv.reader(io.StringIO(result.pop('csv').lstrip('\ufeff'), newline='')))
    result['xlsx_base64'] = base64.b64encode(workbook_bytes(rows)).decode('ascii')
    result['filename'] = result['filename'].removesuffix('.csv') + '.xlsx'
    return result
