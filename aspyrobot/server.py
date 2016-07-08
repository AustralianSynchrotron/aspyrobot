from threading import Lock
from ast import literal_eval
import logging
import inspect
from functools import wraps
import time
from queue import Queue, Empty
import traceback

import zmq
from epics.ca import CAThread, withCA

from .exceptions import RobotError


def foreground_operation(func):
    """
    Decorator to create an operation method that should block other incoming
    operations. Eg a calibration routine.
    """
    @wraps(func)
    def wrapper(server, handle, *args, **kwargs):
        server.operation_update(handle, stage='start')
        if (server.robot.foreground_done.value and
            server._foreground_lock.acquire(False)):
            data, error = _safe_run_operation(server, func, handle, *args, **kwargs)
            server._foreground_lock.release()
        else:
            error = 'busy'
            data = None
        server.operation_update(handle, stage='end', message=data, error=error)
    wrapper._operation_type = 'foreground'
    return wrapper


def background_operation(func):
    """
    Decorator to create an operation method that runs in the background of the
    SPEL application and does not interfere with foreground operations. Eg
    updating a SPEL variable.
    """
    @wraps(func)
    def wrapper(server, handle, *args, **kwargs):
        server.operation_update(handle, stage='start')
        data, error = _safe_run_operation(server, func, handle, *args, **kwargs)
        server.operation_update(handle, stage='end', message=data, error=error)
    wrapper._operation_type = 'background'
    return wrapper


def query_operation(func):
    """
    Decorator to create an operation to query the state of the server. These
    operations must return immediately.
    """
    @wraps(func)
    def wrapper(server, *args, **kwargs):
        data, error = _safe_run_operation(server, func, *args, **kwargs)
        return {'error': error, 'data': data}
    wrapper._operation_type = 'query'
    return wrapper


def _safe_run_operation(server, func, *args, **kwargs):
    """Run a robot operation and catch any exceptions.

    Used by the operation decorators.
    """
    data, error = None, None
    try:
        data = func(server, *args, **kwargs)
    except RobotError as e:
        error = str(e)
        server.logger.error(error)
    except Exception as e:
        error = str(e)
        server.logger.error(traceback.format_exc())
    return data, error


class RobotServer(object):
    """
    The ``RobotServer`` monitors the state of the robot and processes operation
    requests from ``RobotClient``\ s. The robot state is broadcast to clients via a
    Zero-MQ publish/subscribe channel. Operation requests are received via a
    seperate request/reply channel.

    Args:
        robot (Robot): An instance of the aspyrobot.Robot class.
        logger: A logging.Logger object.
        update_addr: An address to create a Zero-MQ socket to broadcast robot
            state updates to clients.
        request_addr: An address to create a Zero-MQ socket to receive operation
            requests from clients.

    """
    def __init__(self, robot, logger=None, update_addr='tcp://*:2000',
                 request_addr='tcp://*:2001'):
        self.robot = robot
        self.logger = logger or logging.getLogger(__name__)
        self.request_addr = request_addr
        self.update_addr = update_addr
        self._zmq_context = zmq.Context()
        self.publish_queue = Queue()
        self._foreground_lock = Lock()
        self._operation_handle = 0
        self._handle_lock = Lock()
        self._shutdown_requested = False

    @withCA
    def setup(self):
        """Set up the server.

        Starts threads and registers for EPICS callbacks.

        """
        self._publisher_thread = CAThread(target=self._publisher,
                                          args=(self.update_addr,), daemon=True)
        self._publisher_thread.start()
        self._request_thread = CAThread(target=self._request_handler,
                                        args=(self.request_addr,), daemon=True)
        self._request_thread.start()
        for attr in self.robot.attrs:
            pv = getattr(self.robot, attr)
            pv.add_callback(self._pv_callback)
        self.robot.client_update.add_callback(self._on_robot_update)
        self.logger.debug('setup complete')

    def shutdown(self):
        """Request the server shuts down.

        Causes the publisher and request threads to exit gracefully.

        """
        self._shutdown_requested = True

    def _pv_callback(self, pvname, value, char_value, type, **kwargs):
        """When robot PVs change send a value update to clients."""
        suffix = pvname.replace(self.robot._prefix, '')
        attr = self.robot.attrs_r[suffix]
        if 'char' in type or 'string' in type:
            value = char_value
        self.values_update({attr: value})

    def _publisher(self, update_addr):
        """Publish robot state updates to clients over Zero-MQ."""
        socket = self._zmq_context.socket(zmq.PUB)
        socket.bind(update_addr)
        while not self._shutdown_requested:
            try:
                message = self.publish_queue.get(timeout=.01)
            except Empty:
                continue
            data = message.get('data', {})
            if not (len(data) == 1 and 'time' in data):  # Don't log time messages
                self.logger.debug('sending to client: %r', message)
            socket.send_json(message)
        socket.close()

    def _request_handler(self, request_addr):
        """Listen for operation requests from clients."""
        socket = self._zmq_context.socket(zmq.REP)
        socket.bind(request_addr)
        while not self._shutdown_requested:
            try:
                message = socket.recv_json(flags=zmq.NOBLOCK)
            except zmq.ZMQError:
                time.sleep(.01)
                continue
            response = self._process_request(message)
            socket.send_json(response)
        socket.close()

    def _process_request(self, message):
        """Parse requests from the clients and take the appropriate action."""
        self.logger.debug('client request: %r', message)
        operation = message.get('operation')
        parameters = message.get('parameters', {})
        try:
            target = getattr(self, operation)
        except (AttributeError, TypeError):
            self.logger.error('operation does not exist: %r', operation)
            return {'error': 'invalid request: operation does not exist'}
        try:
            operation_type = target._operation_type
        except AttributeError:
            self.logger.error('%r must be declared an operation', operation)
            return {'error': 'invalid request: %r not an operation' % operation}
        try:
            sig = inspect.signature(target)
            if operation_type == 'query':
                sig.bind(**parameters)
            else:
                sig.bind(None, **parameters)  # Must accept a handle argument
        except (ValueError, TypeError):
            self.logger.error('invalid arguments for operation %r: %r',
                              operation, parameters)
            return {'error': 'invalid request: incorrect arguments'}
        self.logger.debug('calling: %r with %r', operation, parameters)
        if operation_type == 'query':
            return target(**parameters)
        elif operation_type in {'foreground', 'background'}:
            handle = self._next_handle()
            thread = CAThread(target=target, args=(handle,),
                              kwargs=parameters, daemon=True)
            thread.start()
            return {'error': None, 'handle': handle}
        else:
            return {'error': 'invalid request: unknown operation type'}

    def _next_handle(self):
        """Generate a new operation handle in a thread safe way."""
        with self._handle_lock:
            self._operation_handle += 1
            return self._operation_handle

    def _on_robot_update(self, char_value, **_):
        """Handle special update messages from SPEL.

        These messages use Python dictionary literal syntax and contain a key
        for the variable to be set. We call `update_x` method with the other
        key/values from the dictionary supplied as keyword arguments.

        """
        try:
            message = literal_eval(char_value)
        except SyntaxError:
            return self.logger.error('Invalid update message: %r', char_value)
        attr = message.pop('set')
        try:
            method = getattr(self, 'update_' + attr)
        except AttributeError:
            return self.logger.warning('Unhandled robot update: %r', char_value)
        try:
            method(**message)
        except TypeError:
            self.logger.error('Invalid method signature for update: %r', message)

    def operation_update(self, handle, message='', stage='update', error=None):
        """Add an operation update to the queue to be sent clients.

        Args:
            handle (int): Operation handle.
            message (str): Message to be sent to clients.
            stage (str): `'start'`, `'update'` or `'end'`
            error (str): Error message.

        """
        self.publish_queue.put({
            'type': 'operation',
            'stage': stage,
            'handle': handle,
            'message': message,
            'error': error,
        })

    def values_update(self, update):
        """Add an robot attribute value update to the queue to be sent clients.

        Args:
            update (dict): robot attributes and their values. For example:
                `{'safety_gate': 1, 'motors_on': 0}`

        """
        self.publish_queue.put({'type': 'values', 'data': update})

    @query_operation
    def refresh(self):
        """Query operation to fetch the latest values of the robot state.

        This method should be overridden if the server maintains additional state
        information that needs to be sent to the clients.

        """
        return self.robot.snapshot()

    @background_operation
    def clear(self, handle, level):
        """
        Clear robot state.

        Args:
            level (str): `'status`' or `'all'`

        """
        self.logger.warning('clear: %r', level)
        self.robot.run_background_task('ResetRobotStatus', level)
