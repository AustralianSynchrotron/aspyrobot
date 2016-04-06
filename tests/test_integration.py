from threading import Thread
from types import MethodType
import time

import pytest
from mock import MagicMock
import epics

from aspyrobot import RobotClient, RobotServer
from aspyrobot.server import query_operation


@pytest.yield_fixture
def server(monkeypatch):
    monkeypatch.setattr(epics.ca.CAThread, 'run', Thread.run)
    server = RobotServer(robot=MagicMock(), logger=MagicMock())
    server.setup()
    yield server
    server.shutdown()
    time.sleep(.05)


@pytest.fixture
def client():
    client = RobotClient()
    client.setup()
    return client


def test_queries_work(server, client):
    @query_operation
    def query(server): return {'x': 1}
    server.query = MethodType(query, server)
    response = client.run_operation('query')
    assert response == {'error': None, 'data': {'x': 1}}
