import zmq
from threading import Thread, Lock
from six.moves.queue import Queue


class RobotClient(object):

    def __init__(self, request_addr='tcp://localhost:8876',
                 update_addr='tcp://localhost:8877'):
        self.delegate = None
        self._request_addr = request_addr
        self._update_addr = update_addr
        self._context = zmq.Context()
        self._request_queue = Queue()
        self._reply_queue = Queue()
        self._operation_lock = Lock()

    def setup(self):
        self._request_thread = Thread(target=self._request_monitor,
                                      args=(self._request_addr,))
        self._update_thread = Thread(target=self._update_monitor,
                                     args=(self._update_addr,))
        self._request_thread.daemon = True
        self._update_thread.daemon = True
        self._request_thread.start()
        self._update_thread.start()
        self.refresh()

    def _request_monitor(self, addr):
        socket = self._context.socket(zmq.REQ)
        socket.connect(addr)
        while True:
            self._handle_request(socket)  # Blocks between requests

    def _handle_request(self, socket):
        request = self._request_queue.get()
        socket.send_json(request)
        reply = socket.recv_json()
        self._reply_queue.put(reply)

    def _update_monitor(self, addr):
        socket = self._context.socket(zmq.SUB)
        socket.connect(addr)
        socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            self._handle_update(socket)  # Blocks between updates

    def _handle_update(self, socket):
        message = socket.recv_json()
        if message['type'] == 'values':
            self._handle_values(message.get('data', {}))

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

    def run_operation(self, operation, **parameters):
        with self._operation_lock:
            self._request_queue.put({
                'operation': operation,
                'parameters': parameters,
            })
            reply = self._reply_queue.get()
        return reply

    def refresh(self):
        response = self.run_operation('refresh')
        self.__dict__.update(response.get('data', {}))
