from realtime_voice_typing.hotkey import parse_hotkey


def test_parse_function_key():
    assert parse_hotkey("f8") == (0, 0x77)


def test_parse_with_modifiers():
    assert parse_hotkey("ctrl+alt+space") == (0x0001 | 0x0002, 0x20)


def test_parse_single_letter():
    assert parse_hotkey("a") == (0, ord("A"))


def test_parse_rejects_unknown_key():
    try:
        parse_hotkey("not-a-key")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
