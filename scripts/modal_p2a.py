#!/usr/bin/env python3
"""Retired P1-only Modal smoke entrypoint; refuses before any GPU allocation."""
import sys


def main():
    raise SystemExit(
        'Modal P2a smoke is retired: its mounted p1-dataset.tar.gz and P1 MD5s are legacy. '
        'No GPU was requested. Use the V2-gated, manifest-pinned Colab smoke path instead.'
    )


if __name__ == '__main__':
    main()
