from cap_to_talk.text import normalize_for_typing, strip_wrapping_quotes


def test_normalizes_typography_and_preserves_paragraphs():
    value = "  Hello   “world”…  \n\n\nSecond — paragraph. "

    assert normalize_for_typing(value) == 'Hello "world"...\n\nSecond - paragraph.'


def test_strips_only_matching_wrapping_quotes():
    assert strip_wrapping_quotes('"hello"') == "hello"
    assert strip_wrapping_quotes("'hello'") == "hello"
    assert strip_wrapping_quotes("\"hello'") == "\"hello'"
