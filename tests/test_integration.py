from aspyrobot import RobotClient, RobotServer
from aspyrobot.server import query_operation
import pytest
from mock import MagicMock
from types import MethodType


@pytest.fixture
def server():
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
