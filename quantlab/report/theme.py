"""The visual system shared by the dashboard and exported reports.

A research instrument, not a trading terminal: ink on cool paper in light mode,
graphite in dark mode, one indigo accent for the strategy, amber for the
benchmark, and semantic green/red used ONLY for gains and losses. Numbers are
set in IBM Plex Mono so columns of figures line up.
"""
from __future__ import annotations

FONT_SANS = "IBM Plex Sans"
FONT_MONO = "IBM Plex Mono"
FONT_URL = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&"
            "family=IBM+Plex+Sans:wght@400;500;600;700&display=swap")

LIGHT = {"bg": "#F5F6F8", "surface": "#FFFFFF", "ink": "#12161D", "muted": "#5C6573", "line": "#E1E5EB",
         "accent": "#3550C8", "accent_soft": "#E6EAFB", "bench": "#B7791F", "pos": "#14805E", "neg": "#C23B36",
         "series": ["#3550C8", "#B7791F", "#14805E", "#8A4FB8", "#C23B36", "#2C8C9E", "#6B7280"]}
DARK = {"bg": "#0D1015", "surface": "#151A21", "ink": "#E6E9EE", "muted": "#97A0AD", "line": "#262D37",
        "accent": "#8BA3FF", "accent_soft": "#1C2440", "bench": "#E2B24E", "pos": "#3FC79B", "neg": "#EF7A72",
        "series": ["#8BA3FF", "#E2B24E", "#3FC79B", "#C79BF2", "#EF7A72", "#5FC4D4", "#A3AAB5"]}


def palette(dark: bool = False) -> dict:
    return DARK if dark else LIGHT
