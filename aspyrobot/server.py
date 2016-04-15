from threading import Lock
from ast import literal_eval
import logging
import inspect
from functools import wraps
import time
from queue import Queue, Empty

import zmq
from epics.ca import CAThread, withCA


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
            try:
                message = func(server, handle, *args, **kwargs)
                error = None
            except Exception as e:
                message = None
                error = str(e)
            server._foreground_lock.release()
        else:
            error = 'busy'
            message = None
        server.operation_update(handle, stage='end', message=message, error=error)
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
        try:
            message = func(server, handle, *args, **kwargs)
            error = None
        except Exception as e:
            message = None
            error = str(e)
        server.operation_update(handle, stage='end', message=message, error=error)
    wrapper._operation_type = 'background'
    return wrapper


def query_operation(func):
    """
    Decorator to create an operation to query the state of the server. These
    operations must return immediately.
    """
    @wraps(func)
    def wrapper(server, *args, **kwargs):
        return func(server, *args, **kwargs)
    wrapper._operation_type = 'query'
    return wrapper


class RobotServer(object):

    def __init__(self, robot, logger=None, request_addr='tcp://*:8876',
                 update_addr='tcp://*:8877'):
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
        self._publisher_thread = CAThread(target=self._publisher,
                                          args=(self.update_addr,), daemon=True)
        self._publisher_thread.start()
        self._request_thread = CAThread(target=self._request_handler,
                                        args=(self.request_addr,), daemon=True)
        self._request_thread.start()
        for attr, pv in self.robot._pvs.items():
            pv.add_callback(self._pv_callback)
        self.robot.PV('client_update').add_callback(self._on_robot_update)
        self.logger.debug('setup complete')

    def shutdown(self):
        self._shutdown_requested = True

    def _pv_callback(self, pvname, value, char_value, type, **kwargs):
        # TODO: Too tightly coupled with robot class
        suffix = pvname.replace(self.robot._prefix, '')
        attr = self.robot.attrs_r[suffix]
        if 'char' in type or 'string' in type:
            value = char_value
        self.values_update({attr: value})

    def _publisher(self, update_addr):
        socket = self._zmq_context.socket(zmq.PUB)
        socket.bind(update_addr)
        while not self._shutdown_requested:
            try:
                message = self.publish_queue.get(timeout=.01)
            except Empty:
                continue
            if not (len(message) == 1 and 'time' in message):
                self.logger.debug('sending to client: %r', message)
            socket.send_json(message)
        socket.close()

    def _request_handler(self, request_addr):
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
                # Must accept a handle argument
                sig.bind(None, **parameters)
        except (ValueError, TypeError):
            self.logger.error('invalid arguments for operation %r: %r',
                              operation, parameters)
            return {'error': 'invalid request: incorrect arguments'}
        self.logger.debug('calling: %r with %r', operation, parameters)
        if operation_type == 'query':
            return self._process_query_request(target, parameters)
        elif operation_type in {'foreground', 'background'}:
            return self._process_operation_request(target, parameters)
        else:
            return {'error': 'invalid request: unknown operation type'}

    def _process_query_request(self, target, parameters):
        try:
            data = target(**parameters)
            response = {'error': None, 'data': data}
        except Exception as e:
            response = {'error': str(e)}
        return response

    def _process_operation_request(self, target, parameters):
        handle = self._next_handle()
        thread = CAThread(target=target, args=(handle,),
                          kwargs=parameters, daemon=True)
        thread.start()
        return {'error': None, 'handle': handle}

    def _next_handle(self):
        with self._handle_lock:
            self._operation_handle += 1
            return self._operation_handle

    def _on_robot_update(self, char_value, **_):
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
        self.publish_queue.put({
            'type': 'operation',
            'stage': stage,
            'handle': handle,
            'message': message,
            'error': error,
        })

    def values_update(self, update):
        self.publish_queue.put({'type': 'values', 'data': update})


    @query_operation
    def refresh(self):
        return {}
