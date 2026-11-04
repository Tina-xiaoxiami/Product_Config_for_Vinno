"""Synthetic Office structure fixtures; no visual or model approval is implied."""
import hashlib
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from docx import Document
from openpyxl import Workbook

from app.services import knowledge_content as service


def docx_bytes():
    doc=Document();doc.add_paragraph('');doc.add_heading('Section',level=1)
    table=doc.add_table(rows=2,cols=3)
    table.cell(0,0).text='Merged';table.cell(0,0).merge(table.cell(0,1));table.cell(0,2).text='Value'
    table.cell(1,0).text='Speed';table.cell(1,2).text='2 mm'
    doc.add_paragraph('Final paragraph')
    stream=BytesIO();doc.save(stream);return stream.getvalue()


def xlsx_bytes():
    book=Workbook();sheet=book.active;sheet.title='CN'
    sheet['A5']='Speed';sheet['C5']='2 mm';sheet['D5']='=1+1'
    sheet.merge_cells('A7:B7');sheet['A7']='Merged'
    stream=BytesIO();book.save(stream);book.close();return stream.getvalue()


def test_docx_body_order_real_indices_and_physical_merged_cells():
    raw=docx_bytes();blocks=service.extract_office_blocks(raw,'.docx')
    assert [b.locator['kind'] for b in blocks]==['paragraph','table_row','table_row','paragraph']
    assert blocks[0].locator['paragraph_index']==2
    assert blocks[-1].locator['paragraph_index']==3
    assert blocks[-1].locator['body_index']>blocks[1].locator['body_index']
    row=blocks[1].locator
    assert row['table_index']==1 and row['row_index']==1
    assert len(row['cells'])==2 and row['cells'][0]['grid_span']==2
    assert all(b.locator['source_sha256']==hashlib.sha256(raw).hexdigest() for b in blocks)
    assert all(b.page_number is None for b in blocks)
    chunks=service.build_document_chunks(blocks)
    assert chunks[0]['locator']==blocks[0].locator


def test_xlsx_preserves_sheet_rows_empty_column_coordinates_and_formula_source():
    blocks=service.extract_office_blocks(xlsx_bytes(),'.xlsx')
    row=blocks[0].locator
    assert row['sheet_name']=='CN' and row['sheet_index']==1 and row['row_index']==5
    assert row['range']=='A5:D5'
    assert [c['cell'] for c in row['cells']]==['A5','C5','D5']
    assert row['cells'][-1]['value_type']=='formula'
    assert row['cells'][-1]['text']=='=1+1'
    assert row['formula_state']=='not_evaluated'
    assert blocks[1].locator['cells'][0]['merged_range']=='A7:B7'
    assert blocks[0].source_ref=='CN!A5:D5'


@pytest.mark.parametrize('suffix,data,mime',[('.xls',b'legacy','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    ('.docx',b'not zip',None),('.docx',xlsx_bytes(),None),('.xlsx',docx_bytes(),None),
    ('.xlsx',xlsx_bytes(),'application/pdf')])
def test_unsupported_or_mismatched_formats_fail_explicitly(suffix,data,mime):
    with pytest.raises(service.KnowledgeContentError):service.extract_office_blocks(data,suffix,mime)


def test_package_limits_are_checked_before_library_parsing(monkeypatch):
    monkeypatch.setattr(service,'MAX_OFFICE_EXPANDED_BYTES',10)
    with pytest.raises(service.KnowledgeContentError,match='上限'):service.extract_office_blocks(docx_bytes(),'.docx')


def test_duplicate_zip_members_are_not_ambiguous_sources():
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','x');z.writestr('word/document.xml','x');z.writestr('word/document.xml','y')
    with pytest.raises(service.KnowledgeContentError):service.extract_office_blocks(stream.getvalue(),'.docx')


def test_xml_dtd_and_entity_payload_is_rejected():
    stream=BytesIO()
    with ZipFile(stream,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>');z.writestr('_rels/.rels','<Relationships/>')
        z.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY y "attack">]><x>&y;</x>')
    with pytest.raises(service.KnowledgeContentError):service.extract_office_blocks(stream.getvalue(),'.docx')


def test_office_version_does_not_invalidate_pdf_or_text_extractors(tmp_path):
    assert service.document_extractor_version(tmp_path/'a.docx',None)==service.OFFICE_EXTRACTOR_VERSION
    assert service.document_extractor_version(tmp_path/'a.xlsx',None)==service.OFFICE_EXTRACTOR_VERSION
    assert service.document_extractor_version(tmp_path/'a.pdf',None)==service.EXTRACTOR_VERSION
    assert service.document_extractor_version(tmp_path/'a.txt',None)==service.EXTRACTOR_VERSION


def test_sparse_exaggerated_dimensions_are_bounded(monkeypatch):
    monkeypatch.setattr(service,'MAX_OFFICE_CELLS',2)
    with pytest.raises(service.KnowledgeContentError,match='上限'):service.extract_office_blocks(xlsx_bytes(),'.xlsx')


def test_xlsx_cell_limits_precede_library_object_allocation(monkeypatch):
    monkeypatch.setattr(service,'MAX_OFFICE_CELLS',2)
    monkeypatch.setattr(service,'_xlsx_blocks',lambda *args:pytest.fail('library allocated before bounds'))
    with pytest.raises(service.KnowledgeContentError,match='上限'):service.extract_office_blocks(xlsx_bytes(),'.xlsx')


def test_docx_body_index_counts_unsupported_xml_children_without_pretending_to_extract_them():
    from docx.oxml import OxmlElement
    doc=Document();doc.add_paragraph('First');doc.add_paragraph('Last')
    doc.element.body.insert(1,OxmlElement('w:sdt'))
    stream=BytesIO();doc.save(stream)
    blocks=service.extract_office_blocks(stream.getvalue(),'.docx')
    assert [b.locator['body_index'] for b in blocks]==[1,3]


def test_formula_cell_has_its_own_not_evaluated_marker():
    block=service.extract_office_blocks(xlsx_bytes(),'.xlsx')[0]
    assert block.locator['cells'][-1]['formula_state']=='not_evaluated'
