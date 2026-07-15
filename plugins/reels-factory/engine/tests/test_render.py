from reels_factory.render import parse_loudnorm_json

# Реальный stderr ffmpeg 8.1.1 loudnorm-замера (print_format=json).
LOUDNORM_STDERR = """\
[Parsed_loudnorm_0 @ 0000021be69b1300]
{
\t"input_i" : "-21.75",
\t"input_tp" : "-18.06",
\t"input_lra" : "0.00",
\t"input_thresh" : "-31.75",
\t"output_i" : "-13.95",
\t"output_tp" : "-10.27",
\t"output_lra" : "0.00",
\t"output_thresh" : "-23.95",
\t"normalization_type" : "dynamic",
\t"target_offset" : "-0.05"
}
"""


def test_parse_loudnorm_json_реальный_вывод():
    m = parse_loudnorm_json(LOUDNORM_STDERR)
    assert m is not None
    assert m["input_i"] == -21.75
    assert m["input_tp"] == -18.06
    assert m["input_lra"] == 0.0
    assert m["input_thresh"] == -31.75
    assert m["target_offset"] == -0.05


def test_parse_loudnorm_json_мусор_возвращает_none():
    assert parse_loudnorm_json("no json here") is None
    assert parse_loudnorm_json('{"input_i": "не число"}') is None
    assert parse_loudnorm_json('{"output_i": "-13.95"}') is None  # нет input_i
