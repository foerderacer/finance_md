from __future__ import annotations

import pytest

from finance_md.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    return Workspace.init(tmp_path / "finances")


@pytest.fixture
def ws_with_accounts(ws):
    ws.create_account("Checking", "bank", "EUR")
    ws.create_account("Savings", "savings", "EUR")
    ws.create_account("Cash", "cash", "USD")
    return ws
