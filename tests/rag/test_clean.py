import sys
sys.path.append("packages/rag/clean")
import clean

def test_clean_empty():
    res = clean.clean({})
    assert res["output"] == ""

def test_clean_removes_number_lines():
    text = """Some text here
6
More text here"""
    res = clean.clean({"input": text})
    assert "6" not in res["output"]
    assert "Some text here" in res["output"]
    assert "More text here" in res["output"]

def test_clean_removes_strange_characters():
    text = "This has ââ strange characters"
    res = clean.clean({"input": text})
    assert "ââ" not in res["output"]
    assert "This has" in res["output"]
    assert "strange characters" in res["output"]

def test_clean_removes_empty_lines():
    text = """Line 1

Line 2


Line 3"""
    res = clean.clean({"input": text})
    lines = res["output"].split('\n')
    # Should only have 3 non-empty lines
    assert len(lines) == 3

def test_clean_normalizes_quotes():
    text = "He said \u201chello\u201d and \u2018goodbye\u2019"
    res = clean.clean({"input": text})
    assert '"' in res["output"]
    assert "'" in res["output"]

def test_clean_converts_corrupted_bullets():
    """Test that corrupted bullet points (â from PDF) are converted to dashes"""
    text = """Introduction
â First item
â Second item
Normal text"""
    res = clean.clean({"input": text})
    # Should convert â to - at start of line
    assert "- First item" in res["output"]
    assert "- Second item" in res["output"]
    # Should not contain â anymore
    assert "â" not in res["output"]
