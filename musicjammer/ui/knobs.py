"""Knob maths: where a parameter's value sits on a 0..1 dial, and how to print it."""

from __future__ import annotations

import math

from ..audio import Param


def to_norm(param: Param, value: float) -> float:
    if param.log:
        return math.log(value / param.min) / math.log(param.max / param.min)
    return (value - param.min) / (param.max - param.min)


def from_norm(param: Param, norm: float) -> float:
    norm = min(1.0, max(0.0, norm))
    if param.log:
        return param.min * (param.max / param.min) ** norm
    return param.min + norm * (param.max - param.min)


def nudge(param: Param, value: float | str, steps: float) -> float | str:
    """Turn a knob by `steps` (40 steps span the dial), or step through a choice."""
    if param.is_choice:
        choices = param.choices
        return choices[(choices.index(value) + round(steps)) % len(choices)]
    return from_norm(param, to_norm(param, value) + steps / 40)


def format_value(param: Param, value: float | str) -> str:
    if param.is_choice:
        return str(value)
    if param.unit == "dB":
        return "0 dB" if abs(value) < 0.05 else f"{value:+.1f} dB"
    if param.unit == "s":
        return f"{value * 1000:.0f} ms" if value < 1 else f"{value:.2f} s"
    return f"{value:.0%}"
