"""Tests for the markdown→HTML email rendering."""

from podworm.cli import _render_summary_html


def test_table_renders_as_html_table():
    md = (
        "Summary intro.\n\n"
        "| Topic | Detail |\n"
        "|-------|--------|\n"
        "| AI    | foo    |\n"
        "| ML    | bar    |\n"
    )
    html = _render_summary_html(md)
    assert "<table>" in html
    assert "<thead>" in html
    assert "<th>Topic</th>" in html
    assert "<td>AI</td>" in html
    assert "| Topic | Detail |" not in html


def test_strikethrough_renders():
    html = _render_summary_html("~~old~~ new")
    assert "<s>old</s>" in html


def test_html_envelope_present():
    html = _render_summary_html("hello")
    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "max-width:640px" in html
    assert "<p>hello</p>" in html
