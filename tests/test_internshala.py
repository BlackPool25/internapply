"""Tests for Internshala stipend parsing logic.

Tests the ``parse_stipend()`` function which handles various Internshala
stipend formats: ranges, single values, unpaid markers, and edge cases.
"""

from __future__ import annotations

import pytest

from internapply.discovery.internshala import (
    parse_stipend,
    _clean_number,
    _passes_stipend_filter,
    _passes_location_filter,
)


# ---------------------------------------------------------------------------
# Tests — parse_stipend
# ---------------------------------------------------------------------------


class TestParseStipend:
    """Stipend string parsing — 4 required combinations + 2 edge cases."""

    def test_stipend_parsing_range(self):
        """"₹10,000-15,000 /month" → (10000, 15000, True)."""
        result = parse_stipend("₹10,000-15,000 /month")
        assert result == (10000, 15000, True), f"Expected (10000, 15000, True) but got {result}"

    def test_stipend_parsing_range_with_dash(self):
        """"₹10,000–15,000 /month" (en-dash) → (10000, 15000, True)."""
        result = parse_stipend("₹10,000–15,000 /month")
        assert result == (10000, 15000, True), f"Expected (10000, 15000, True) but got {result}"

    def test_stipend_parsing_unpaid(self):
        """"Unpaid" → (0, 0, False)."""
        result = parse_stipend("Unpaid")
        assert result == (0, 0, False), f"Expected (0, 0, False) but got {result}"

    def test_stipend_parsing_performance_based(self):
        """"Performance based" → (0, 0, False)."""
        result = parse_stipend("Performance based")
        assert result == (0, 0, False), f"Expected (0, 0, False) but got {result}"

    def test_stipend_parsing_single(self):
        """"₹5,000 /month" → (5000, 5000, True)."""
        result = parse_stipend("₹5,000 /month")
        assert result == (5000, 5000, True), f"Expected (5000, 5000, True) but got {result}"

    def test_stipend_parsing_lump_sum(self):
        """"₹15,000 lump sum" → (15000, 15000, True)."""
        result = parse_stipend("₹15,000 lump sum")
        assert result == (15000, 15000, True), f"Expected (15000, 15000, True) but got {result}"

    def test_stipend_parsing_none(self):
        """None input → (None, None, False)."""
        result = parse_stipend(None)
        assert result == (None, None, False), f"Expected (None, None, False) but got {result}"

    def test_stipend_parsing_empty(self):
        """Empty string → (None, None, False)."""
        result = parse_stipend("")
        assert result == (None, None, False), f"Expected (None, None, False) but got {result}"

    def test_stipend_parsing_whitespace(self):
        """Whitespace-only string → (None, None, False)."""
        result = parse_stipend("   ")
        assert result == (None, None, False), f"Expected (None, None, False) but got {result}"

    def test_stipend_parsing_no_symbol_range(self):
        """Plain number range without ₹ symbol → parsed correctly."""
        result = parse_stipend("5,000-10,000 /month")
        assert result == (5000, 10000, True), f"Expected (5000, 10000, True) but got {result}"

    def test_stipend_parsing_negotiable(self):
        """"Negotiable" → (0, 0, False)."""
        result = parse_stipend("Negotiable")
        assert result == (0, 0, False), f"Expected (0, 0, False) but got {result}"


# ---------------------------------------------------------------------------
# Tests — helper: _clean_number
# ---------------------------------------------------------------------------


class TestCleanNumber:
    """Number cleaning helper."""

    def test_clean_number_simple(self):
        assert _clean_number("5000") == 5000

    def test_clean_number_with_commas(self):
        assert _clean_number("10,000") == 10000

    def test_clean_number_large(self):
        assert _clean_number("1,50,000") == 150000


# ---------------------------------------------------------------------------
# Tests — filter helpers
# ---------------------------------------------------------------------------


class TestFilters:
    """Stipend and location filter helpers."""

    def test_passes_stipend_filter_above_threshold(self):
        card = {"stipend_raw": "₹15,000 /month"}
        assert _passes_stipend_filter(card, 5000) is True
        assert card["stipend_min"] == 15000
        assert card["stipend_max"] == 15000
        assert card["is_paid"] is True

    def test_passes_stipend_filter_below_threshold(self):
        card = {"stipend_raw": "₹3,000 /month"}
        assert _passes_stipend_filter(card, 5000) is False
        assert card["stipend_min"] == 3000
        assert card["is_paid"] is True

    def test_passes_location_filter_remote(self):
        assert _passes_location_filter({"location": "Remote"}, ["Bangalore"]) is True

    def test_passes_location_filter_specific(self):
        assert _passes_location_filter({"location": "Bangalore"}, ["Bangalore"]) is True

    def test_passes_location_filter_no_match(self):
        assert _passes_location_filter({"location": "Mumbai"}, ["Bangalore"]) is False
