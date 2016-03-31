from aspyrobot import RobotClient, RobotServer
from aspyrobot.server import query_operation
import pytest
from mock import MagicMock
import epics
from types import MethodType
from threading import Thread


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(epics.ca.CAThread, 'run', Thread.run)
    server = RobotServer(robot=MagicMock(), logger=MagicMock())
    server.setup()
    return server


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
