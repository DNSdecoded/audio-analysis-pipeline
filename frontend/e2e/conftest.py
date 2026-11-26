"""Shared fixtures for the browser suites: one Playwright/Chromium instance per run."""

from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()
