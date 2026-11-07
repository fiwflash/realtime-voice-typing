from realtime_voice_typing.inserter import codepoints


def test_codepoints_thai():
    assert codepoints("ไทย") == [ord("ไ"), ord("ท"), ord("ย")]


def test_codepoints_english():
    assert codepoints("hi") == [104, 105]


def test_codepoints_drops_non_bmp():
    assert codepoints("a😀b") == [97, 98]
