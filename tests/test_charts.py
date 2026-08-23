"""SVG generation — output must be well-formed XML, not just a string."""

import xml.etree.ElementTree as ET

import pytest

from radar import charts


def parse(svg: str) -> ET.Element:
    """Fails loudly on malformed markup."""
    return ET.fromstring(svg)


class TestSparkline:
    def test_output_is_valid_xml(self):
        root = parse(charts.sparkline([1.0, 5.0, 3.0, 9.0]))
        assert root.tag.endswith("svg")

    def test_respects_requested_size(self):
        root = parse(charts.sparkline([1.0, 2.0], width=300, height=60))
        assert root.get("width") == "300"
        assert root.get("height") == "60"

    def test_rising_series_uses_the_up_colour(self):
        svg = charts.sparkline([1.0, 10.0])
        assert charts.PALETTE["up"] in svg

    def test_falling_series_uses_the_down_colour(self):
        svg = charts.sparkline([10.0, 1.0])
        assert charts.PALETTE["down"] in svg

    def test_empty_series_renders_placeholder(self):
        svg = charts.sparkline([])
        parse(svg)
        assert "no data yet" in svg

    def test_single_point_does_not_divide_by_zero(self):
        parse(charts.sparkline([42.0]))

    def test_flat_series_does_not_divide_by_zero(self):
        parse(charts.sparkline([7.0, 7.0, 7.0]))

    def test_all_points_stay_inside_the_viewbox(self):
        width, height, pad = 200, 50, 4.0
        coords = charts._points([1.0, 99.0, 50.0, 3.0], width, height, pad)
        for x, y in coords:
            assert pad - 0.01 <= x <= width - pad + 0.01
            assert pad - 0.01 <= y <= height - pad + 0.01


class TestBarChart:
    def test_output_is_valid_xml(self):
        parse(charts.bar_chart([("Data", 100.0), ("ML", 50.0)]))

    def test_height_grows_with_row_count(self):
        one = int(parse(charts.bar_chart([("A", 1.0)])).get("height"))
        three = int(parse(charts.bar_chart([("A", 1.0), ("B", 2.0), ("C", 3.0)])).get("height"))
        assert three > one

    def test_negative_values_use_the_down_colour(self):
        svg = charts.bar_chart([("Falling", -500.0)])
        assert charts.PALETTE["down"] in svg

    def test_all_zero_values_do_not_divide_by_zero(self):
        parse(charts.bar_chart([("A", 0.0), ("B", 0.0)]))

    def test_escapes_labels_that_would_break_xml(self):
        svg = charts.bar_chart([("Web & <backend>", 10.0)])
        root = parse(svg)
        texts = [el.text for el in root.iter() if el.tag.endswith("text")]
        assert "Web & <backend>" in texts

    def test_empty_input_renders_placeholder(self):
        assert "no data yet" in charts.bar_chart([])


class TestFormatting:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (950.0, "950"),
            (1500.0, "1.5k"),
            (2_400_000.0, "2.4M"),
            (-1500.0, "-1.5k"),
            (0.0, "0"),
        ],
    )
    def test_human_readable_numbers(self, value, expected):
        assert charts._fmt(value) == expected
