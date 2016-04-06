from threading import Thread
from concurrent.futures import ThreadPoolExecutor

import pytest
from mock import MagicMock, call

from aspyrobot.client import RobotClient


@pytest.fixture
def client():
    return RobotClient()


def test_run_operation(client):
    expected_response = {'error': None}
    client._reply_queue.put(expected_response)
    expected_request = {'operation': 'set_lid', 'parameters': {'value': 1}}
    assert client.run_operation('set_lid', value=1) == expected_response
    assert client._request_queue.get() == expected_request


def test_handle_request(client):
    mock_socket = MagicMock()
    mock_socket.recv_json.return_value = {'error': None}
    request = {'operation': 'probe'}
    client._request_queue.put(request)
    client._handle_request(mock_socket)
    assert client._reply_queue.get() == {'error': None}
    assert mock_socket.send_json.call_args == call(request)


def test_handle_update_sets_attrs_for_values(client):
    mock_socket = MagicMock()
    message = {'type': 'values', 'data': {'lid_open_status': 'open'}}
    mock_socket.recv_json.return_value = message
    client._handle_update(mock_socket)
    assert client.lid_open_status == 'open'


def test_handle_update_calls_callbacks(client):
    client.on_lid_open_status = MagicMock()
    mock_socket = MagicMock()
    message = {'type': 'values', 'data': {'lid_open_status': 'open'}}
    mock_socket.recv_json.return_value = message
    client._handle_update(mock_socket)
    assert client.on_lid_open_status.call_args == call('open')


def test_handle_calls_delegate_callbacks(client):
    client.delegate = MagicMock()
    mock_socket = MagicMock()
    message = {'type': 'values', 'data': {'lid_open_status': 'open'}}
    mock_socket.recv_json.return_value = message
    client._handle_update(mock_socket)
    assert client.delegate.on_lid_open_status.call_args == call('open')


def test_refresh(client):
    client.run_operation = MagicMock()
    client.run_operation.return_value = {'data': {'some_robot_attr': 1}}
    client.refresh()
    assert client.run_operation.call_args == call('refresh')
    assert client.some_robot_attr == 1


def test_run_operation_is_thread_safe(client):
    def processor():
        while True:
            request = client._request_queue.get()
            client._reply_queue.put(request)
    Thread(target=processor, daemon=True).start()
    with ThreadPoolExecutor() as executor:
        futures = {operation: executor.submit(client.run_operation, operation)
                   for operation in range(10)}
        for operation, future in futures.items():
            response = future.result()
            assert response['operation'] == operation
