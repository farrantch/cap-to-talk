from unittest.mock import patch

from caps_talk.x11 import _type


def test_type_uses_stdin_for_multiline_text():
    with patch("caps_talk.x11.subprocess.run") as run:
        _type("first\n\nsecond", 2)

    assert run.call_args.kwargs["input"] == "first\n\nsecond"
    assert run.call_args.kwargs["text"] is True
    assert run.call_args.args[0][-2:] == ["--file", "-"]
