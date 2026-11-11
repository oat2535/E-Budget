import io
import re
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

from budget_app.dashboard_service import MONTH_KEYS, PCT_KEYS, round2

# Strip characters invalid in XML 1.0
_INVALID_XML_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Exact 33-column specification matching Dashboard.xlsx
EXPORT_COLUMNS = (
    ('row_order', 'row_order', 'int', 10),
    ('general_ledger_code', 'general_ledger_code', 'str', 18),
    ('gl_name', 'gl_name', 'str', 42),
    ('actual_value', 'Act จริง', 'num', 16),
    ('per_month_value', 'ต่อเดือน', 'num', 15),
    ('annualized_value', '12', 'num', 16),
    ('sales_ratio', 'สัดส่วน/ยอดขาย', 'num', 16),
    ('growth_rate', '% การโต', 'num', 13),
    *((k, k, 'num', 15) for k in MONTH_KEYS),
    ('total', 'total', 'num', 17),
    *((k, k, 'num', 12) for k in PCT_KEYS),
)

_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Dashboard" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

_WORKBOOK_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# Styles table:
# Fonts: 0=regular dark, 1=bold dark, 2=bold white (header)
# Fills: 0=none, 1=gray125 (required by OOXML), 2=navy (#1E3A8A), 3=header (#EEF2F7), 4=subtotal (#F7F3E8), 5=pnl (#DBEAFE)
# Borders: 0=none, 1=thin light gray (#CBD5E1)
# numFmts: 164='#,##0.00;[Red]-#,##0.00', 165='0'
# cellXfs indices:
#   0: default
#   1: table header row (bold white, navy fill, center, border)
#   2: regular int center (row_order)
#   3: regular str left
#   4: regular num 2dp
#   5: group-header int center (#EEF2F7, bold)
#   6: group-header str left (#EEF2F7, bold)
#   7: group-header num 2dp (#EEF2F7, bold)
#   8: subtotal int center (#F7F3E8, bold)
#   9: subtotal str left (#F7F3E8, bold)
#  10: subtotal num 2dp (#F7F3E8, bold)
#  11: major P&L int center (#DBEAFE, bold)
#  12: major P&L str left (#DBEAFE, bold)
#  13: major P&L num 2dp (#DBEAFE, bold)
_STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="2">
    <numFmt numFmtId="164" formatCode="#,##0.00;[Red]-#,##0.00"/>
    <numFmt numFmtId="165" formatCode="0"/>
  </numFmts>
  <fonts count="3">
    <font><sz val="11"/><color rgb="FF0F172A"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FF0F172A"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
  </fonts>
  <fills count="6">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1E3A8A"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFEEF2F7"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF7F3E8"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDBEAFE"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFCBD5E1"/></left>
      <right style="thin"><color rgb="FFCBD5E1"/></right>
      <top style="thin"><color rgb="FFCBD5E1"/></top>
      <bottom style="thin"><color rgb="FFCBD5E1"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="14">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="165" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="164" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="165" fontId="1" fillId="4" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="164" fontId="1" fillId="4" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="165" fontId="1" fillId="5" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="164" fontId="1" fillId="5" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>"""


def _col_letter(index_1based: int) -> str:
    chars = []
    n = index_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(65 + rem))
    return ''.join(reversed(chars))


def _sanitize_text(val) -> str:
    text = '' if val is None else str(val)
    return escape(_INVALID_XML_RE.sub('', text))


def _style_for_row(row_dict, kind: str) -> int:
    if row_dict.get('is_pnl_summary') and row_dict.get('general_ledger_code') in ('FH1-H3', 'SP-B', 'H6', 'H8', 'FH8'):
        base = 11
    elif row_dict.get('row_type') == 'subtotal':
        base = 8
    elif row_dict.get('row_type') == 'header':
        base = 5
    else:
        base = 2

    if kind == 'int':
        return base
    if kind == 'str':
        return base + 1
    return base + 2


def build_dashboard_xlsx(dashboard_payload: dict) -> bytes:
    """Generate a formatted OOXML .xlsx byte payload matching Dashboard.xlsx (33 columns, 2dp).

    Implemented with pure Python stdlib (zero third-party runtime dependencies).
    """
    rows = dashboard_payload.get('rows') or []
    last_col_letter = _col_letter(len(EXPORT_COLUMNS))
    last_row_num = len(rows) + 1

    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        f'<dimension ref="A1:{last_col_letter}{last_row_num}"/>',
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">',
        '<pane xSplit="3" ySplit="1" topLeftCell="D2" activePane="bottomRight" state="frozen"/>',
        '</sheetView></sheetViews>',
        '<sheetFormatPr defaultRowHeight="19"/>',
        '<cols>',
    ]
    for col_idx, (_, _, _, width) in enumerate(EXPORT_COLUMNS, start=1):
        parts.append(f'<col min="{col_idx}" max="{col_idx}" width="{width}" customWidth="1"/>')
    parts.append('</cols><sheetData>')

    # Header row
    header_cells = []
    for col_idx, (_, header_title, _, _) in enumerate(EXPORT_COLUMNS, start=1):
        ref = f'{_col_letter(col_idx)}1'
        header_cells.append(f'<c r="{ref}" s="1" t="inlineStr"><is><t>{_sanitize_text(header_title)}</t></is></c>')
    parts.append(f'<row r="1" ht="24" customHeight="1">{"".join(header_cells)}</row>')

    # Data rows
    for row_idx, row_dict in enumerate(rows, start=2):
        cells = []
        for col_idx, (field_key, _, kind, _) in enumerate(EXPORT_COLUMNS, start=1):
            ref = f'{_col_letter(col_idx)}{row_idx}'
            style_id = _style_for_row(row_dict, kind)
            raw_val = row_dict.get(field_key)
            if kind == 'int':
                int_val = int(raw_val or 0)
                cells.append(f'<c r="{ref}" s="{style_id}"><v>{int_val}</v></c>')
            elif kind == 'num':
                num_dec: Decimal = round2(raw_val)
                cells.append(f'<c r="{ref}" s="{style_id}"><v>{num_dec:.2f}</v></c>')
            else:
                text_val = _sanitize_text(raw_val)
                cells.append(f'<c r="{ref}" s="{style_id}" t="inlineStr"><is><t>{text_val}</t></is></c>')
        parts.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    parts.append(f'</sheetData><autoFilter ref="A1:{last_col_letter}{last_row_num}"/></worksheet>')
    sheet_xml = ''.join(parts)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES_XML)
        zf.writestr('_rels/.rels', _RELS_XML)
        zf.writestr('xl/workbook.xml', _WORKBOOK_XML)
        zf.writestr('xl/_rels/workbook.xml.rels', _WORKBOOK_RELS_XML)
        zf.writestr('xl/styles.xml', _STYLES_XML)
        zf.writestr('xl/worksheets/sheet1.xml', sheet_xml)

    return buf.getvalue()
