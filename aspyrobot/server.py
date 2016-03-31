import zmq
from epics.ca import CAThread
from six.moves.queue import Queue
from threading import Lock
from ast import literal_eval
import inspect
import logging
from functools import wraps


def foreground_operation(func):
    @wraps(func)
    def wrapper(server, handle, *args, **kwargs):
        server.operation_update(handle, stage='start')
        message = None
        error = None
        if not server.foreground_operation_lock.acquire(False):
            error = 'busy'
        else:
            try:
                message = func(server, handle, *args, **kwargs)
            except Exception as e:
                error = str(e)
            server.foreground_operation_lock.release()
        server.operation_update(handle, stage='end', message=message, error=error)
    wrapper._operation_type = 'foreground'
    return wrapper


def query_operation(func):
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
        self.context = zmq.Context()
        self.publish_queue = Queue()
        self.foreground_operation_lock = Lock()
        self.operation_handle = 0
        self.handle_lock = Lock()

    def setup(self):
        self.publisher_thread = CAThread(target=self.publisher,
                                         args=(self.update_addr,))
        self.publisher_thread.daemon = True
        self.publisher_thread.start()
        self.request_thread = CAThread(target=self.request_handler,
                                       args=(self.request_addr,))
        self.request_thread.daemon = True
        self.request_thread.start()
        for attr, pv in self.robot._pvs.items():
            pv.add_callback(self.pv_callback)
        self.robot.PV('client_update').add_callback(self.on_robot_update)
        self.logger.debug('setup complete')

    def pv_callback(self, pvname, value, char_value, type, **kwargs):
        suffix = pvname.replace(self.robot._prefix, '')
        attr = self.robot.attrs_r[suffix]
        if type == 'ctrl_char':
            value = char_value
        self.publish_queue.put({attr: value})

    def publisher(self, update_addr):
        socket = self.context.socket(zmq.PUB)
        socket.bind(update_addr)
        while True:
            message = self.publish_queue.get()
            if not (len(message) == 1 and 'time' in message):
                self.logger.debug('sending to client: %r', message)
            socket.send_json(message)

    def request_handler(self, request_addr):
        socket = self.context.socket(zmq.REP)
        socket.bind(request_addr)
        while True:
            message = socket.recv_json()
            response = self.process_request(message)
            socket.send_json(response)

    def process_request(self, message):
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
            try:
                data = target(**parameters)
                response = {'error': None, 'data': data}
            except Exception as e:
                response = {'error': str(e)}
            return response
        with self.handle_lock:
            self.operation_handle += 1
            handle = self.operation_handle
        thread = CAThread(target=target, args=(handle,), kwargs=parameters)
        thread.daemon = True
        thread.start()
        return {'error': None, 'handle': handle}

    def on_robot_update(self, char_value, **_):
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
