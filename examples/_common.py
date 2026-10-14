"""Shared setup for the examples: a throwaway workspace and section headings."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def workspace(name: str) -> Path:
    """Point quantlab at a fresh temporary home, lake and SEC store, so an example never
    touches your real data. Must run before any quantlab object is created."""
    root = Path(tempfile.mkdtemp(prefix=f"quantlab-{name}-"))
    os.environ["QUANTLAB_HOME"] = str(root / "home")
    os.environ["QUANTLAB_LAKE"] = str(root / "lake")
    os.environ["QUANTLAB_SEC_DB"] = str(root / "sec" / "insider.duckdb")
    return root


def section(title: str) -> None:
    print(f"\n{title}\n{'─' * len(title)}")


def table(df, **kw) -> None:
    import pandas as pd
    with pd.option_context("display.width", 140, "display.max_columns", 20, "display.float_format", "{:,.4g}".format):
        print(df.to_string(index=False, **kw))
