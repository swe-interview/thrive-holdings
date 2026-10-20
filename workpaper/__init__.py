"""Classify a prepared document segment into a workpaper section."""

from schema import Workpaper, WorkpaperSection, load_workpaper
from workpaper.classify import Classification, classify_segment, classify_segments
from workpaper.segment import Segment

__all__ = [
    "Classification",
    "Segment",
    "Workpaper",
    "WorkpaperSection",
    "classify_segment",
    "classify_segments",
    "load_workpaper",
]
