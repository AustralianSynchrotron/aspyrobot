from time import time

from epics import PV, poll


DELAY_TO_PROCESS = .3


class RobotError(Exception):
    """ Error on robot controller """


class Robot(object):

    attrs = {
        'run_args': 'RA_CMD',
        'task_message': 'TASKMSG_MON',
        'task_progress': 'TASKPROG_MON',
        'task_result': 'RRESULT_MON',
        'model': 'MODEL_MON',
        'time': 'TIME_MON',
        'at_home': 'ATHOME_STATUS',
        'motors_on': 'MOTOR_STATUS',
        'motors_on_command': 'MOTOR_CMD',
        'toolset': 'TOOL_MON',
        'toolset_command': 'TOOL_CMD',
        'foreground_done': 'FDONE_STATUS',
        'system_error_message': 'ERRMSG_MON',
        'foreground_error': 'FERR_STATUS',
        'foreground_error_message': 'FOREEMSG_MON',
        'safety_gate': 'SAFETYON_STATUS',
        'generic_command': 'GENERIC_CMD',
        'generic_float_command': 'GENERICFLOAT_CMD',
        'generic_string_command': 'GENERICSTR_CMD',
        'client_update': 'CLIENTUPDATE_MON',
        'client_response': 'CLIENTRESP_MON',
        'closest_point': 'CLOSESTP_MON',
    }
    attrs_r = {v: k for k, v in attrs.items()}

    def __init__(self, prefix, **kwargs):
        for attr, suffix in self.attrs.items():
            pv = PV(prefix + suffix, form='ctrl')
            setattr(self, attr, pv)

    def snapshot(self):
        data = {}
        for attr in self.attrs:
            pv = getattr(self, attr)
            if 'string' in pv.type or 'char' in pv.type:
                value = pv.char_value
            else:
                value = pv.value
            data[attr] = value
        return data

    def execute(self, attr):
        pv = getattr(self, attr)
        pv.put(1, wait=True)
        pv.put(0)

    def run_foreground_operation(self, name, args='', timeout=.5):
        if not self.foreground_done.get():
            raise RobotError('busy')
        self.run_args.put(args)
        poll(DELAY_TO_PROCESS)
        self.generic_command.put(name)
        self._wait_for_foreground_busy(timeout)
        self._wait_for_foreground_free()
        poll(DELAY_TO_PROCESS)
        return self.task_result.get(as_string=True)

    def _wait_for_foreground_busy(self, timeout):
        t0 = time()
        while time() < t0 + timeout:
            if self.foreground_done.get() == 0:
                break
            poll(.01)
        else:
            raise RobotError('operation failed to start')

    def _wait_for_foreground_free(self):
        while True:
            if self.foreground_done.get() == 1:
                break
            poll(.01)
