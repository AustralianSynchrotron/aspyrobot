from epics import Device


class RobotDevice(Device):

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
        super(RobotDevice, self).__init__(prefix, **kwargs)
        for attr, suffix in self.attrs.items():
            self.add_pv(prefix + suffix, attr=attr, form='ctrl')

    def execute(self, attr):
        self.put(attr, 1, wait=True)
        self.put(attr, 0)
