from threading import Thread, Lock
from queue import Queue

import zmq

from .exceptions import RobotError


class RobotClient(object):

    def __init__(self, request_addr='tcp://localhost:8876',
                 update_addr='tcp://localhost:8877'):
        self.delegate = None
        self._request_addr = request_addr
        self._update_addr = update_addr
        self._zmq_context = zmq.Context()
        self._request_queue = Queue()
        self._reply_queue = Queue()
        self._operation_lock = Lock()
        self._operation_callbacks = {}

    def setup(self):
        self._request_thread = Thread(target=self._request_monitor,
                                      args=(self._request_addr,), daemon=True)
        self._update_thread = Thread(target=self._update_monitor,
                                     args=(self._update_addr,), daemon=True)
        self._request_thread.start()
        self._update_thread.start()
        self.refresh()

    def _request_monitor(self, addr):
        socket = self._zmq_context.socket(zmq.REQ)
        socket.connect(addr)
        while True:
            self._handle_request(socket)  # Blocks between requests

    def _handle_request(self, socket):
        request = self._request_queue.get()
        socket.send_json(request)
        reply = socket.recv_json()
        self._reply_queue.put(reply)

    def _update_monitor(self, addr):
        socket = self._zmq_context.socket(zmq.SUB)
        socket.connect(addr)
        socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            self._handle_update(socket)  # Blocks between updates

    def _handle_update(self, socket):
        message = socket.recv_json()
        if message['type'] == 'values':
            self._handle_values(message.get('data', {}))
        elif message['type'] == 'operation':
            with self._operation_lock:
                callback = self._operation_callbacks.get(message['handle'])
            if callback:
                callback(handle=message.get('handle'),
                         stage=message.get('stage'),
                         message=message.get('message'),
                         error=message.get('error'))

    def _handle_values(self, values):
        for attr, value in values.items():
            setattr(self, attr, value)
            callback = getattr(self, 'on_' + attr, None)
            if callback is not None:
                callback(value)
            if self.delegate is not None:
                callback = getattr(self.delegate, 'on_' + attr, None)
                if callback is not None:
                    callback(value)

    def run_query(self, operation, **parameters):
        with self._operation_lock:
            self._request_queue.put({
                'operation': operation,
                'parameters': parameters,
            })
            reply = self._reply_queue.get()
        if reply.get('error') is not None:
            raise RobotError(reply['error'])
        return reply.get('data', {})

    def run_operation(self, operation, callback=None, **parameters):
        with self._operation_lock:
            self._request_queue.put({'operation': operation,
                                     'parameters': parameters})
            reply = self._reply_queue.get()
            if reply.get('error') is not None:
                raise ValueError(reply['error'])  # Invalid operation or parameters
            if callback:
                handle = reply['handle']
                self._operation_callbacks[handle] = callback
            return reply

    def refresh(self):
        data = self.run_query('refresh')
        self.__dict__.update(data)
