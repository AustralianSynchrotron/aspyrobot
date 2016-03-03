import zmq
from six.moves.queue import Queue
from threading import Thread, Lock, ThreadError
from ast import literal_eval
import logging


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

    def setup(self):
        self.publisher_thread = Thread(target=self.publisher,
                                       args=(self.update_addr,))
        self.publisher_thread.daemon = True
        self.publisher_thread.start()
        self.request_thread = Thread(target=self.request_handler,
                                     args=(self.request_addr,))
        self.request_thread.daemon = True
        self.request_thread.start()
        for attr, pv in self.robot._pvs.items():
            pv.add_callback(self.pv_callback)
        self.robot.PV('foreground_done').add_callback(
            self.foreground_done_callback
        )
        self.robot.PV('client_update').add_callback(self.on_robot_update)
        self.on_robot_update(self.robot.PV('client_update').char_value)
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
            self.logger.debug('client request: %r', message)
            operation = message.get('operation')
            parameters = message.get('parameters', {})
            if operation and getattr(self, operation, None):
                response = getattr(self, operation)(**parameters)
                if response is None:
                    response = {'error': None}
            else:
                self.logger.error('invalid client request: %r', message)
                response = {'error': 'invalid request'}
            self.logger.debug('response to client: %r', response)
            socket.send_json(response)

    def foreground_done_callback(self, value, **_):
        if value == 0:
            self.foreground_operation_lock.acquire(False)
        elif value == 1:
            try:
                self.foreground_operation_lock.release()
            except ThreadError:
                pass

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
