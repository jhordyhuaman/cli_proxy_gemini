import pytest

from mgm.protocol.xml_parser import TextEvent, ToolCallEvent, ToolStartEvent, XMLToolParser


def parse(chunks):
    parser = XMLToolParser()
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.flush())
    merged = []
    for event in events:
        if isinstance(event, TextEvent) and merged and isinstance(merged[-1], TextEvent):
            merged[-1] = TextEvent(merged[-1].text + event.text)
        else:
            merged.append(event)
    return merged


SAMPLE = 'antes <tool name="escribir" path="a.txt">contenido</tool> después'


def test_plain_text_only():
    assert parse(["hola, ¿cómo estás?"]) == [TextEvent("hola, ¿cómo estás?")]


def test_single_tool_one_chunk():
    events = parse(['<tool name="escribir" path="a.txt">hola</tool>'])
    assert events == [
        ToolStartEvent("escribir", {"path": "a.txt"}),
        ToolCallEvent("escribir", {"path": "a.txt"}, "hola"),
    ]


def test_text_before_and_after_tool():
    events = parse([SAMPLE])
    assert events == [
        TextEvent("antes "),
        ToolStartEvent("escribir", {"path": "a.txt"}),
        ToolCallEvent("escribir", {"path": "a.txt"}, "contenido"),
        TextEvent(" después"),
    ]


@pytest.mark.parametrize("split", range(len(SAMPLE) + 1))
def test_any_two_way_split_matches_single_feed(split):
    assert parse([SAMPLE[:split], SAMPLE[split:]]) == parse([SAMPLE])


def test_char_by_char_matches_single_feed():
    assert parse(list(SAMPLE)) == parse([SAMPLE])


def test_multiple_tools_and_text():
    text = 'a <tool name="x">1</tool> b <tool name="y" modo="r">2</tool> c'
    events = parse([text])
    assert events == [
        TextEvent("a "),
        ToolStartEvent("x", {}),
        ToolCallEvent("x", {}, "1"),
        TextEvent(" b "),
        ToolStartEvent("y", {"modo": "r"}),
        ToolCallEvent("y", {"modo": "r"}, "2"),
        TextEvent(" c"),
    ]


def test_unclosed_tool_at_end_of_stream():
    events = parse(['<tool name="escribir" path="a.txt">cuerpo sin cierre'])
    assert events == [
        ToolStartEvent("escribir", {"path": "a.txt"}),
        ToolCallEvent("escribir", {"path": "a.txt"}, "cuerpo sin cierre", closed=False),
    ]


def test_partial_close_tag_at_end_is_tolerated():
    events = parse(['<tool name="x">cuerpo</to'])
    assert events[-1] == ToolCallEvent("x", {}, "cuerpo</to", closed=False)


def test_garbage_that_looks_like_tag_is_text():
    assert parse(["mira <tools y <toolkit cosas"]) == [
        TextEvent("mira <tools y <toolkit cosas")
    ]


def test_angle_brackets_in_plain_text():
    assert parse(["si a < b y c > d"]) == [TextEvent("si a < b y c > d")]


def test_incomplete_opener_at_end_becomes_text():
    assert parse(['texto <tool name="x']) == [TextEvent('texto <tool name="x')]


def test_self_closing_tool():
    events = parse(['<tool name="ping"/>'])
    assert events == [
        ToolStartEvent("ping", {}),
        ToolCallEvent("ping", {}, ""),
    ]


def test_tool_body_keeps_angle_brackets_and_newlines():
    events = parse(['<tool name="cmd">echo "a < b"\nls</tool>'])
    assert events[-1] == ToolCallEvent("cmd", {}, 'echo "a < b"\nls')


def test_parser_can_be_reused_after_flush():
    parser = XMLToolParser()
    parser.feed('<tool name="x">sin cierre')
    parser.flush()
    assert parse_with(parser, ["hola"]) == [TextEvent("hola")]


def parse_with(parser, chunks):
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.flush())
    return events
