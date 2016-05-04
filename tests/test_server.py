from types import MethodType
import time
from unittest.mock import MagicMock, call

import pytest

from aspyrobot.server import (RobotServer, query_operation, foreground_operation,
                              background_operation)
from aspyrobot.exceptions import RobotError


@pytest.yield_fixture
def server():
    robot = MagicMock(_prefix='MOCK_ROBOT:')
    robot.foreground_done.value = 1
    yield RobotServer(robot=robot, logger=MagicMock())


def operation_updates(server):
    while True:
        message = server.publish_queue.get(timeout=1.)
        if message['type'] != 'operation':
            continue
        yield message
        if message['stage'] == 'end':
            break


def test_process_request(server):
    server.calibrate = MagicMock(_operation_type='foreground', return_value=None)
    message = {'operation': 'calibrate', 'parameters': {'target': 'middle'}}
    response = server._process_request(message)
    assert response['error'] is None
    assert response['handle'] == 1
    time.sleep(.05)
    assert server.calibrate.call_args == call(1, target='middle')


def test_process_request_missing_operation(server):
    response = server._process_request({})
    assert 'invalid request' in response['error']


def test_process_request_returns_error_for_invalid_operation(server):
    message = {'operation': 'does_not_exist', 'parameters': {}}
    response = server._process_request(message)
    assert 'does not exist' in response['error']


def test_process_request_returns_error_for_bad_function(server):
    @foreground_operation
    def method_missing_self(): pass
    server.method_missing_self = MethodType(method_missing_self, server)
    message = {'operation': 'method_missing_self'}
    response = server._process_request(message)
    assert 'invalid request' in response['error']


def test_process_request_returns_error_for_incorrect_parameters(server):
    @foreground_operation
    def calibrate(server, handle, target=None): pass
    server.calibrate = MethodType(calibrate, server)
    message = {'operation': 'calibrate', 'parameters': {'wrong_name': 'middle'}}
    response = server._process_request(message)
    assert 'invalid request' in response['error']


def test_process_request_requires_operation_type(server):
    # No operation decorator
    def method_without_operation_type(server, handle): pass
    server.operation = MethodType(method_without_operation_type, server)
    message = {'operation': 'operation'}
    response = server._process_request(message)
    assert 'invalid request' in response['error']


def test_process_request_handles_background_operation(server):
    @background_operation
    def operation(server, handle): return 'done'
    server.operation = MethodType(operation, server)
    response = server._process_request({'operation': 'operation'})
    assert response['error'] is None
    end_update = list(operation_updates(server))[-1]
    assert end_update['message'] == 'done'


def test_process_background_request_ignores_operation_lock(server):
    @background_operation
    def operation(server, handle): return 'done'
    server.operation = MethodType(operation, server)
    server._foreground_lock.acquire(False)
    response = server._process_request({'operation': 'operation'})
    assert response['error'] is None
    end_update = list(operation_updates(server))[-1]
    assert end_update['message'] == 'done'


def test_query_operation(server):
    @query_operation
    def query(server): return {'x': 1}
    server.query = MethodType(query, server)
    response = server._process_request({'operation': 'query'})
    assert response == {'error': None, 'data': {'x': 1}}


def test_query_operation_with_error(server):
    @query_operation
    def query(server): raise RobotError('Whoops!')
    server.query = MethodType(query, server)
    response = server._process_request({'operation': 'query'})
    assert response['error'] == 'Whoops!'
    assert server.logger.error.call_args == call('Whoops!')


def test_query_operation_with_general_exception_logs_traceback(server):
    @query_operation
    def bad_operation(server): raise Exception('Bad bad happened')
    bad_operation(server)
    assert 'Traceback' in server.logger.error.call_args[0][0]


def test_foreground_operation_requests_fail_if_foreground_locked(server):
    @foreground_operation
    def do_something(server, handle): pass
    server.do_something = MethodType(do_something, server)
    server._foreground_lock.acquire()
    server._process_request({'operation': 'do_something'})
    end_update = list(operation_updates(server))[-1]
    assert 'busy' in end_update['error']
    # Check foreground is still locked
    assert server._foreground_lock.acquire(False) is False


def test_foreground_operation_requests_fail_if_foreground_busy(server):
    @foreground_operation
    def do_something(server, handle): pass
    server.do_something = MethodType(do_something, server)
    server.robot.foreground_done.value = 0
    server._process_request({'operation': 'do_something'})
    end_update = list(operation_updates(server))[-1]
    assert 'busy' in end_update['error']


def test_foreground_operation_with_robot_error(server):
    @foreground_operation
    def bad_operation(server, handle): raise RobotError('Bad bad happened')
    server.bad_operation = MethodType(bad_operation, server)
    server._process_request({'operation': 'bad_operation'})
    end_update = list(operation_updates(server))[-1]
    assert 'Bad bad happened' in end_update['error']
    assert server.logger.error.call_args == call('Bad bad happened')
    # Check foreground is unlocked
    assert server._foreground_lock.acquire(False) is True


def test_foreground_operation_sends_message(server):
    @foreground_operation
    def operation(server, handle):
        return 'all good'
    operation(server, 1)
    end_update = list(operation_updates(server))[-1]
    assert end_update['message'] == 'all good'


def test_foreground_operation_with_general_exception_logs_traceback(server):
    @foreground_operation
    def bad_operation(server, handle): raise Exception('Bad bad happened')
    bad_operation(server, handle=1)
    assert 'Traceback' in server.logger.error.call_args[0][0]


def test_background_request_with_robot_error(server):
    @background_operation
    def bad_operation(server, handle): raise RobotError('Bad bad happened')
    bad_operation(server, handle=1)
    end_update = list(operation_updates(server))[-1]
    assert end_update['error'] == 'Bad bad happened'
    assert server.logger.error.call_args == call('Bad bad happened')


def test_background_operation_with_general_exception_logs_traceback(server):
    @background_operation
    def bad_operation(server, handle): raise Exception('Bad bad happened')
    bad_operation(server, handle=1)
    assert 'Traceback' in server.logger.error.call_args[0][0]


def test_on_robot_update(server):
    server.update_some_attr = MagicMock()
    server._on_robot_update("{'set': 'some_attr', 'value': 5, 'extra': 'info'}")
    assert server.update_some_attr.call_args == call(value=5, extra='info')


def test_on_robot_update_with_bad_string(server):
    server._on_robot_update("{")
    assert server.logger.error.called is True


def test_on_robot_update_missing_method(server):
    server._on_robot_update("{'set': 'unexpected_attr'}")
    assert server.logger.warning.called is True


def test_on_robot_update_with_unexpected_attributes(server):
    def update_some_attr(value):
        pass
    server.update_some_attr = update_some_attr
    server._on_robot_update("{'set': 'some_attr', 'value': 5, 'extra': 'info'}")
    assert server.logger.error.called is True


def test_pv_callback_creates_attr_message(server):
    server.robot.attrs_r = {'MOTOR_STATUS': 'motors_on'}
    server._pv_callback(pvname='MOCK_ROBOT:MOTOR_STATUS', value=1,
                        char_value='1', type='ctrl_enum')
    update = server.publish_queue.get()
    assert update['type'] == 'values'
    assert update['data'] == {'motors_on': 1}


def test_pv_callback_uses_char_value_for_char_arrays(server):
    server.robot.attrs_r = {'CLIENTUPDATE_MON': 'client_update'}
    server._pv_callback(pvname='MOCK_ROBOT:CLIENTUPDATE_MON', value=None,
                        char_value='stringy value', type='ctrl_char')
    update = server.publish_queue.get()
    assert update['type'] == 'values'
    assert update['data'] == {'client_update': 'stringy value'}


def test_pv_callback_uses_char_value_for_strings(server):
    server.robot.attrs_r = {'MODEL_MON': 'model'}
    server._pv_callback(pvname='MOCK_ROBOT:MODEL_MON', value=None,
                        char_value='G6-553S-II', type='time_string')
    update = server.publish_queue.get()
    assert update['type'] == 'values'
    assert update['data'] == {'model': 'G6-553S-II'}


def test_clear(server):
    server.robot.run_foreground_operation.return_value = 'ok'
    server.clear(1, 'all')
    assert server.robot.run_foreground_operation.call_args == call('Clear', 'all')
