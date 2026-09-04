"""Synthetic acoustic fixtures. They test DSP rules, not field accuracy."""

import numpy as np


def silence(ms):
    return bytes(ms * 8 * 2)


def signal(ms, frequencies=(170, 430, 790), amplitude=1800):
    t = np.arange(ms * 8) / 8000
    samples = sum(amplitude * np.sin(2 * np.pi * hz * t) for hz in frequencies)
    return samples.astype(np.int16).tobytes()
