from types import MethodType
import time

import pytest
from mock import MagicMock, call

from aspyrobot.server import (RobotServer, query_operation, foreground_operation,
                              background_operation)


@pytest.yield_fixture
def server():
    yield RobotServer(robot=None, logger=MagicMock())


def test_process_request(server):
    server.calibrate = MagicMock(_operation_type='foreground', return_value=None)
    message = {'operation': 'calibrate', 'parameters': {'target': 'middle'}}
    response = server.process_request(message)
    assert response['error'] is None
    assert response['handle'] == 1
    time.sleep(.05)
    assert server.calibrate.call_args == call(1, target='middle')


def test_process_request_missing_operation(server):
    response = server.process_request({})
    assert 'invalid request' in response['error']


def test_process_request_returns_error_for_invalid_operation(server):
    message = {'operation': 'does_not_exist', 'parameters': {}}
    response = server.process_request(message)
    assert 'does not exist' in response['error']


def test_process_request_returns_error_for_bad_function(server):
    @foreground_operation
    def method_missing_self(): pass
    server.method_missing_self = MethodType(method_missing_self, server)
    message = {'operation': 'method_missing_self'}
    response = server.process_request(message)
    assert 'invalid request' in response['error']


def test_process_request_returns_error_for_incorrect_parameters(server):
    @foreground_operation
    def calibrate(server, handle, target=None): pass
    server.calibrate = MethodType(calibrate, server)
    message = {'operation': 'calibrate', 'parameters': {'wrong_name': 'middle'}}
    response = server.process_request(message)
    assert 'invalid request' in response['error']


def test_process_request_requires_operation_type(server):
    # No operation decorator
    def method_without_operation_type(server, handle): pass
    server.operation = MethodType(method_without_operation_type, server)
    message = {'operation': 'operation'}
    response = server.process_request(message)
    assert 'invalid request' in response['error']


def test_process_request_handles_background_operation(server):
    @background_operation
    def operation(server, handle): return 'done'
    server.operation = MethodType(operation, server)
    response = server.process_request({'operation': 'operation'})
    assert response['error'] is None
    server.publish_queue.get(timeout=.1)  # start update
    end_update = server.publish_queue.get(timeout=.1)
    assert end_update['message'] == 'done'


def test_process_background_request_ignores_operation_lock(server):
    @background_operation
    def operation(server, handle): return 'done'
    server.operation = MethodType(operation, server)
    server.foreground_operation_lock.acquire(False)
    response = server.process_request({'operation': 'operation'})
    assert response['error'] is None
    server.publish_queue.get(timeout=.1)  # start update
    end_update = server.publish_queue.get(timeout=.1)
    assert end_update['message'] == 'done'


def test_query_operation(server):
    @query_operation
    def query(server): return {'x': 1}
    server.query = MethodType(query, server)
    response = server.process_request({'operation': 'query'})
    assert response == {'error': None, 'data': {'x': 1}}


def test_query_operation_with_error(server):
    @query_operation
    def query(server): raise Exception('Whoops!')
    server.query = MethodType(query, server)
    response = server.process_request({'operation': 'query'})
    assert response == {'error': 'Whoops!'}


def test_foreground_operation_requests_fail_if_busy(server):
    @foreground_operation
    def do_something(server, handle): pass
    server.do_something = MethodType(do_something, server)
    server.foreground_operation_lock.acquire(False)
    response = server.process_request({'operation': 'do_something'})
    assert 'busy' in response['error']
    # Check foreground is still locked
    assert server.foreground_operation_lock.acquire(False) is False


def test_foreground_operation_with_error(server):
    @foreground_operation
    def bad_operation(server, handle):
        raise Exception('Bad bad happened')
    server.bad_operation = MethodType(bad_operation, server)
    server.process_request({'operation': 'bad_operation'})
    server.publish_queue.get(timeout=.1)  # start update
    end_update = server.publish_queue.get(timeout=.1)
    assert 'Bad bad happened' in end_update['error']
    # Check foreground is unlocked
    assert server.foreground_operation_lock.acquire(False) is True


def test_foreground_operation_sends_message(server):
    @foreground_operation
    def operation(server, handle):
        return 'all good'
    server.foreground_operation_lock.acquire()
    operation(server, 1)
    server.publish_queue.get(timeout=.1)  # start update
    end_update = server.publish_queue.get(timeout=.1)
    assert end_update['message'] == 'all good'


def test_on_robot_update(server):
    server.update_some_attr = MagicMock()
    server.on_robot_update("{'set': 'some_attr', 'value': 5, 'extra': 'info'}")
    assert server.update_some_attr.call_args == call(value=5, extra='info')


def test_on_robot_update_with_bad_string(server):
    server.on_robot_update("{")
    assert server.logger.error.called is True


def test_on_robot_update_missing_method(server):
    server.on_robot_update("{'set': 'unexpected_attr'}")
    assert server.logger.warning.called is True


def test_on_robot_update_with_unexpected_attributes(server):
    def update_some_attr(value):
        pass
    server.update_some_attr = update_some_attr
    server.on_robot_update("{'set': 'some_attr', 'value': 5, 'extra': 'info'}")
    assert server.logger.error.called is True
