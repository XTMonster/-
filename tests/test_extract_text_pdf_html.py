"""正文抽取的三种介质：纯文本 / HTML / PDF（`tools/kb_fetch/extract_text.py`）。

现代教材与论文的主体是 PDF/网页，而管线原先只会读纯文本——这条测试钉住
"能不能读"，以及**缺依赖时报错而不是静默返回空串**。
"""

from __future__ import annotations

import builtins
import json
import pathlib

import pytest

from tools.kb_fetch import common, extract_text


def _minimal_pdf(text: str) -> bytes:
    """手搓一个最小可读 PDF（带 xref），避免为测试再引一个生成库。"""
    content = f"BT /F1 24 Tf 20 100 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


def test_html_extraction_keeps_visible_text_and_drops_scripts():
    page = ("<!doctype html><html><head><style>p{color:red}</style></head><body>"
            "<h1>构图</h1><p>三分法把主体放在交点。</p>"
            "<script>var x = '别抽我';</script>"
            "<noscript>也不抽</noscript><div>第三段</div></body></html>")
    text = extract_text.strip_html(page)
    assert "构图" in text and "三分法把主体放在交点" in text and "第三段" in text
    assert "别抽我" not in text and "也不抽" not in text and "color:red" not in text


def test_clean_routes_html_through_the_stripper():
    cleaned = extract_text.clean("<html><body><p>低机位让人物显得高大。</p></body></html>",
                                 "http")
    assert cleaned == "低机位让人物显得高大。" or "低机位让人物显得高大" in cleaned
    assert "<p>" not in cleaned


def test_pdf_extraction_reads_the_text_layer():
    pytest.importorskip("pypdf", reason="PDF 是可选开发依赖；缺失时下面的缺依赖用例会覆盖")
    text = extract_text.extract_pdf(_minimal_pdf("BlockDirector previs"))
    assert "BlockDirector previs" in text


def test_missing_pypdf_raises_with_an_install_hint(monkeypatch):
    """缺依赖必须**报错并给出安装命令**——绝不返回空串冒充"抽取成功"。"""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("simulated: pypdf not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(extract_text.ExtractionError) as excinfo:
        extract_text.extract_pdf(_minimal_pdf("Any content"))
    assert "pip install pypdf" in str(excinfo.value)


def test_extract_record_routes_pdf_by_magic_bytes(tmp_path, monkeypatch):
    """路由看的是**抓下来的字节**（`%PDF`），不是 URL 后缀。"""
    monkeypatch.setattr(common, "ROOT", tmp_path)
    pytest.importorskip("pypdf", reason="PDF 是可选开发依赖")
    cache = tmp_path / "work" / "raw" / "abc.txt"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(_minimal_pdf("Locator board"))
    record = {"mode": "http", "cache_path": "work/raw/abc.txt",
              "text": "%PDF-1.4 乱码乱码", "source_ref": {"url": "https://example.test/a.pdf"},
              "domain": "cinematography"}
    text, reason = extract_text.extract_record(record)
    assert not reason and "Locator board" in text


def test_extract_run_records_why_a_source_was_rejected(tmp_path, monkeypatch):
    """抽不出正文也要**留痕**（`work/extract_rejects.jsonl`），不静默丢。"""
    work = tmp_path / "work"
    monkeypatch.setattr(common, "WORK", work)
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(extract_text, "EXTRACTED", work / "extracted.jsonl")
    monkeypatch.setattr(extract_text, "EXTRACT_REJECTS", work / "extract_rejects.jsonl")
    records = [{"mode": "http", "cache_path": "", "text": "   ",
                "source_ref": {"url": "https://example.test/empty"}, "domain": "editing"}]
    out = extract_text.run(records)
    assert out == []
    rejects = [json.loads(line) for line in
               (work / "extract_rejects.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    assert rejects and rejects[0]["reason"] == "empty_after_clean"
    assert rejects[0]["url"] == "https://example.test/empty"
