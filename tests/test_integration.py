from types import MethodType
import time
from unittest.mock import MagicMock

import pytest

from aspyrobot import RobotClient, RobotServer
from aspyrobot.server import query_operation


@pytest.yield_fixture
def server():
    robot = MagicMock()
    robot.snapshot.return_value = {}
    server = RobotServer(robot=robot, logger=MagicMock())
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
    response = client.run_query('query')
    assert response == {'x': 1}


def test_queries_raise_exception(server, client):
    @query_operation
    def query(server): raise Exception('bad bad happened')
    server.query = MethodType(query, server)
    with pytest.raises(Exception) as error:
        client.run_query('query')
    assert str(error.value) == 'bad bad happened'
