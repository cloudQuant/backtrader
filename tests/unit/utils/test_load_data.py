#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for shared data-loading helpers."""

from datetime import datetime

from backtrader.utils import load_data


def _write_mt5_csv(path):
    path.write_text(
        "\n".join(
            [
                "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>",
                "2024.01.01\t00:00\t1.0\t2.0\t0.5\t1.5\t10\t100\t3",
                "2024.01.02\t00:00\t2.0\t3.0\t1.5\t2.5\t20\t200\t4",
                "2024.01.03\t00:00\t3.0\t4.0\t2.5\t3.5\t30\t300\t5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_mt5_csv_reuses_cached_slice_and_returns_copy(tmp_path):
    load_data._read_mt5_csv_cached.cache_clear()
    load_data._slice_mt5_csv_cached.cache_clear()

    path = tmp_path / "sample.tsv"
    _write_mt5_csv(path)

    first = load_data.load_mt5_csv(
        path,
        fromdate=datetime(2024, 1, 2),
        todate=datetime(2024, 1, 3),
    )
    first.iloc[0, first.columns.get_loc("open")] = 999.0

    second = load_data.load_mt5_csv(
        path,
        fromdate=datetime(2024, 1, 2),
        todate=datetime(2024, 1, 3),
    )

    assert load_data._slice_mt5_csv_cached.cache_info().hits >= 1
    assert list(second["open"]) == [2.0, 3.0]


def test_augment_mt5_csv_columns_aligns_selected_columns(tmp_path):
    load_data._read_mt5_csv_cached.cache_clear()
    load_data._slice_mt5_csv_cached.cache_clear()

    path = tmp_path / "sample.tsv"
    _write_mt5_csv(path)

    frame = load_data.load_mt5_csv(
        path,
        fromdate=datetime(2024, 1, 2),
        todate=datetime(2024, 1, 3),
    )
    augmented = load_data.augment_mt5_csv_columns(
        frame,
        path,
        ["spread", "real_volume"],
    )

    assert list(augmented["spread"]) == [4, 5]
    assert list(augmented["real_volume"]) == [200, 300]
