"""Notification-focused unit tests for BtApiStore."""

import datetime as dt

import pytest

from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


def _event_types(store):
    return [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]


def _events(store):
    return [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
