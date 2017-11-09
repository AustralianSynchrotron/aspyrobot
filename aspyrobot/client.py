from threading import Thread, Lock
from queue import Queue

import zmq

from .exceptions import RobotError


class RobotClient:
    """
    ``RobotClient``\ s are used to remotely monitor the robot and initiate
    operations.

    Args:
        update_addr: Address of the ``RobotServer`` update socket.
        request_addr: Address of the ``RobotServer`` operation request socket.

    Attributes:
        status (int): Robot status flag
        current_task (str): Current operation the robot is performing.
        task_message (str): Messages about current foreground task
        task_progress (str): Current task progress
        model (str): Model of the robot
        time (str): Time on robot controller (can be used as a heartbeat monitor)
        at_home (int): Whether the robot is in the home position
        motors_on (int): Whether the robot motors are on
        motors_on_command (int): Value of motors on instruction
        toolset (codes.Toolset): Current toolset the robot is in
        foreground_done (int): Whether the foreground is available
        safety_gate (int): Is the safety gate open
        closest_point (int): Closest labelled point to the robot's coordinates

    """
    def __init__(self, update_addr='tcp://localhost:2000',
                 request_addr='tcp://localhost:2001'):
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
        """
        Set up a request socket to the server and transmit any messages added to
        the request queue.

        """
        socket = self._zmq_context.socket(zmq.REQ)
        socket.connect(addr)
        while True:
            self._handle_request(socket)  # Blocks between requests

    def _handle_request(self, socket):
        """
        Send operation requests to the server and put the reply on a queue.

        """
        request = self._request_queue.get()
        socket.send_json(request)
        reply = socket.recv_json()
        self._reply_queue.put(reply)

    def _update_monitor(self, addr):
        """
        Set up a subscription for updates from the server.

        """
        socket = self._zmq_context.socket(zmq.SUB)
        socket.connect(addr)
        socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            self._handle_update(socket)  # Blocks between updates

    def _handle_update(self, socket):
        """
        Fetch and handle messages from the server. Blocks until a message is
        received.

        """
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
        """
        Set the values received from the server as attributes on self and run
        run event handler methods.

        """
        for attr, value in values.items():
            setattr(self, attr, value)
            callback = getattr(self, 'on_' + attr, None)
            if callback is not None:
                callback(value)
            if self.delegate is not None:
                callback = getattr(self.delegate, 'on_' + attr, None)
                if callback is not None:
                    callback(value)

    def run_query(self, query_name, **parameters):
        """Fetch data from the ``RobotServer``.

        Executes a query method on the robot server and returns the data.

        Args:
            query_name (str): Name of the ``RobotServer`` method to run.
            **parameters: keyword arguments to be passed to the query method.

        Raises:
            RobotError: Error happened on the server.

        """
        with self._operation_lock:
            self._request_queue.put({
                'operation': query_name,
                'parameters': parameters,
            })
            reply = self._reply_queue.get()
        if reply.get('error') is not None:
            raise RobotError(reply['error'])
        return reply.get('data', {})

    def run_operation(self, operation, callback=None, **parameters):
        """Run an operation on the ``RobotServer``.

        Args:
            operation (str): Name of the ``RobotServer`` method to run.
            **parameters: keyword arguments to be passed to the operation method.
            callback: Callback function to receive updates about the operation.
                Should handle arguments:
                ``handle``, ``stage``, ``message``, ``error``

        Raises:
            ValueError: Invalid operation name or parameters.

        """
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

    def clear(self, level, callback=None):
        """
        Clear the robot state.

        Args:
            level (str): 'status' or 'all'
            callback: Callback function to receive operation updates

        """
        return self.run_operation('clear', level=level, callback=callback)
