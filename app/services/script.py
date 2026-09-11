"""Script paragraph parsing and narration-aligned timeline helpers."""

from __future__ import annotations

import html
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

from app.services import subtitle
from app.utils import utils


MIN_SENTENCES_PER_PARAGRAPH = 3
MAX_SENTENCES_PER_PARAGRAPH = 5
_PARAGRAPH_BREAK_RE = re.compile(r"(?:\r?\n[ \t]*){2,}")
_SENTENCE_ENDINGS = frozenset(".,!?;\uff0c\u3002\uff01\uff1f\uff1b")
_CLOSING_MARKS = frozenset("\"'\u2019\u201d\u3009\u300b\u300d\u300f\u3011\u3015\u3017\u3019\u301b")
_SRT_TIME_RE = re.compile(
    r"(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+)[,.](?P<millis>\d+)"
)


@dataclass(frozen=True)
class ScriptTimelineSegment:
    index: int
    text: str
    start: float
    end: float
    duration: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def split_sentences(text: str) -> list[str]:
    """Split multilingual prose into sentences without discarding punctuation."""
    value = str(text or "").strip()
    if not value:
        return []

    sentences: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        buffer.append(char)

        is_numeric_separator = (
            char in ".,\uff0c"
            and index > 0
            and index + 1 < len(value)
            and value[index - 1].isdigit()
            and value[index + 1].isdigit()
        )
        is_boundary = char in _SENTENCE_ENDINGS and not is_numeric_separator
        if char in "\r\n":
            is_boundary = bool("".join(buffer).strip())

        if is_boundary:
            lookahead = index + 1
            while lookahead < len(value) and value[lookahead] in _CLOSING_MARKS:
                buffer.append(value[lookahead])
                lookahead += 1
            sentence = "".join(buffer).strip()
            if sentence:
                sentences.append(sentence)
            buffer = []
            index = lookahead - 1

        index += 1

    trailing = "".join(buffer).strip()
    if trailing:
        sentences.append(trailing)
    return sentences


def _balanced_group_sizes(sentence_count: int) -> list[int]:
    if sentence_count <= MAX_SENTENCES_PER_PARAGRAPH:
        return [sentence_count] if sentence_count else []

    group_count = math.ceil(sentence_count / MAX_SENTENCES_PER_PARAGRAPH)
    while group_count > 1 and sentence_count / group_count < MIN_SENTENCES_PER_PARAGRAPH:
        group_count -= 1

    base_size, remainder = divmod(sentence_count, group_count)
    return [base_size + (1 if index < remainder else 0) for index in range(group_count)]


def group_script_sentences(text: str) -> list[str]:
    """Group an unformatted script into balanced paragraphs of 3-5 sentences."""
    sentences = split_sentences(text)
    if not sentences:
        return []

    return group_spoken_phrases_by_sizes(
        sentences,
        _balanced_group_sizes(len(sentences)),
    )


def group_spoken_phrases_by_sizes(
    phrases: Iterable[str], sizes: Iterable[int]
) -> list[str]:
    """Rebuild paragraphs from ordered phrases and validated group sizes."""
    clean_phrases = [str(phrase).strip() for phrase in phrases if str(phrase).strip()]
    clean_sizes = [int(size) for size in sizes]
    if not clean_phrases or not clean_sizes or sum(clean_sizes) != len(clean_phrases):
        raise ValueError("paragraph sizes must cover every spoken phrase exactly once")
    if any(size <= 0 for size in clean_sizes):
        raise ValueError("paragraph sizes must be positive")

    paragraphs: list[str] = []
    offset = 0
    for size in clean_sizes:
        paragraphs.append(" ".join(clean_phrases[offset : offset + size]).strip())
        offset += size
    return paragraphs


def split_explicit_script_paragraphs(text: str) -> list[str]:
    """Return only the paragraph boundaries explicitly present in the text."""
    value = str(text or "").strip()
    if not value:
        return []
    return [
        part.strip()
        for part in _PARAGRAPH_BREAK_RE.split(value)
        if part.strip()
    ]


def paragraphs_follow_spoken_phrase_limits(paragraphs: Iterable[str]) -> bool:
    """Validate the 3-5 spoken-phrase contract used by smart paragraphing."""
    clean_paragraphs = [
        str(paragraph).strip()
        for paragraph in paragraphs
        if str(paragraph).strip()
    ]
    if not clean_paragraphs:
        return False

    counts = [count_sentences(paragraph) for paragraph in clean_paragraphs]
    total_count = sum(counts)
    if total_count <= MAX_SENTENCES_PER_PARAGRAPH:
        return len(clean_paragraphs) == 1 and total_count > 0
    return all(
        MIN_SENTENCES_PER_PARAGRAPH <= count <= MAX_SENTENCES_PER_PARAGRAPH
        for count in counts
    )


def split_script_paragraphs(text: str) -> list[str]:
    """
    Return explicit blank-line paragraphs, or auto-group an unformatted script.

    Blank lines are the manual editing contract. Once a user inserts them, their
    boundaries are preserved even when a paragraph intentionally falls outside
    the normal 3-5 sentence recommendation.
    """
    value = str(text or "").strip()
    if not value:
        return []

    explicit = split_explicit_script_paragraphs(value)
    if len(explicit) > 1:
        return explicit
    return group_script_sentences(value)


def format_script_paragraphs(paragraphs: Iterable[str]) -> str:
    return "\n\n".join(str(paragraph).strip() for paragraph in paragraphs if str(paragraph).strip())


def count_sentences(text: str) -> int:
    return len(split_sentences(text))


def _alignment_text(text: str) -> str:
    value = utils.normalize_script_for_subtitle_matching(text or "")
    value = html.unescape(value)
    value = re.sub(r"[\[\](){}]", "", value)
    return re.sub(r"[_\W]+", "", value, flags=re.UNICODE).casefold()


def _consume_timed_text(
    paragraphs: list[str],
    timed_items: Iterable[tuple[float, float, str]],
) -> list[tuple[float, float]]:
    targets = [_alignment_text(paragraph) for paragraph in paragraphs]
    if not targets or any(not target for target in targets):
        return []

    matches: list[tuple[float, float]] = []
    target_index = 0
    current_text = ""
    current_start: float | None = None
    current_end = 0.0

    for start, end, content in timed_items:
        if target_index >= len(targets):
            break
        normalized = _alignment_text(content)
        if not normalized:
            continue
        if current_start is None:
            current_start = max(float(start), 0.0)
        current_end = max(float(end), current_start)
        current_text += normalized

        target = targets[target_index]
        if current_text == target:
            matches.append((current_start, current_end))
            target_index += 1
            current_text = ""
            current_start = None
            continue

        if not target.startswith(current_text):
            return []

    return matches if len(matches) == len(paragraphs) else []


def _submaker_timed_items(sub_maker: Any) -> list[tuple[float, float, str]]:
    if sub_maker is None:
        return []

    cues = getattr(sub_maker, "cues", None) or []
    if cues:
        return [
            (
                cue.start.total_seconds(),
                cue.end.total_seconds(),
                str(getattr(cue, "content", "") or ""),
            )
            for cue in cues
        ]

    offsets = getattr(sub_maker, "offset", None) or []
    subs = getattr(sub_maker, "subs", None) or []
    return [
        (start / 10_000_000, end / 10_000_000, str(content or ""))
        for (start, end), content in zip(offsets, subs)
    ]


def _srt_seconds(value: str) -> float:
    match = _SRT_TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    return (
        int(match.group("hours")) * 3600
        + int(match.group("minutes")) * 60
        + int(match.group("seconds"))
        + int(match.group("millis")) / (10 ** len(match.group("millis")))
    )


def _subtitle_timed_items(subtitle_path: str) -> list[tuple[float, float, str]]:
    if not subtitle_path or not Path(subtitle_path).is_file():
        return []

    result: list[tuple[float, float, str]] = []
    for _, time_range, text in subtitle.file_to_subtitles(subtitle_path):
        try:
            start_text, end_text = time_range.split(" --> ", 1)
            result.append((_srt_seconds(start_text), _srt_seconds(end_text), text))
        except (TypeError, ValueError) as exc:
            logger.warning(
                "skip invalid subtitle timing while building script timeline: "
                f"range={time_range!r}, error={exc}"
            )
    return result


def _paragraph_weight(text: str) -> float:
    clean = utils.remove_pause_tags(text or "")
    cjk_chars = len(re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", clean))
    words = len(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", clean))
    other_chars = len(
        re.findall(
            r"[^\W\d_\u3400-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z]",
            clean,
            flags=re.UNICODE,
        )
    )
    pauses = count_sentences(clean) * 0.35
    return max(cjk_chars / 4.2 + words / 2.7 + other_chars / 4.0 + pauses, 0.1)


def _weighted_timeline(
    paragraphs: list[str], audio_duration: float
) -> list[ScriptTimelineSegment]:
    weights = [_paragraph_weight(paragraph) for paragraph in paragraphs]
    total_weight = sum(weights) or float(len(paragraphs))
    cursor = 0.0
    segments: list[ScriptTimelineSegment] = []
    for index, (paragraph, weight) in enumerate(zip(paragraphs, weights), start=1):
        end = (
            audio_duration
            if index == len(paragraphs)
            else cursor + audio_duration * weight / total_weight
        )
        segments.append(
            ScriptTimelineSegment(
                index=index,
                text=paragraph,
                start=cursor,
                end=end,
                duration=max(end - cursor, 0.01),
            )
        )
        cursor = end
    return segments


def build_script_timeline(
    paragraphs: list[str],
    *,
    audio_duration: float,
    sub_maker: Any = None,
    subtitle_path: str = "",
) -> list[ScriptTimelineSegment]:
    """Build a continuous paragraph timeline covering the full narration."""
    clean_paragraphs = [str(paragraph).strip() for paragraph in paragraphs if str(paragraph).strip()]
    try:
        total_duration = float(audio_duration)
    except (TypeError, ValueError):
        total_duration = 0.0
    if not clean_paragraphs or not math.isfinite(total_duration) or total_duration <= 0:
        return []

    matches = _consume_timed_text(clean_paragraphs, _submaker_timed_items(sub_maker))
    source = "tts"
    if not matches:
        matches = _consume_timed_text(
            clean_paragraphs,
            _subtitle_timed_items(subtitle_path),
        )
        source = "subtitle"

    if not matches:
        logger.warning(
            "fall back to weighted script paragraph timing because narration "
            "timestamps could not be aligned"
        )
        return _weighted_timeline(clean_paragraphs, total_duration)

    boundaries = [0.0]
    for start, _ in matches[1:]:
        boundaries.append(min(max(float(start), boundaries[-1]), total_duration))
    boundaries.append(total_duration)

    if any(end <= start for start, end in zip(boundaries, boundaries[1:])):
        logger.warning(
            f"fall back to weighted script paragraph timing because {source} "
            "timestamps are not strictly increasing"
        )
        return _weighted_timeline(clean_paragraphs, total_duration)

    return [
        ScriptTimelineSegment(
            index=index,
            text=paragraph,
            start=boundaries[index - 1],
            end=boundaries[index],
            duration=boundaries[index] - boundaries[index - 1],
        )
        for index, paragraph in enumerate(clean_paragraphs, start=1)
    ]
