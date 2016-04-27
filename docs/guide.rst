Developers Guide
================

The classes in ASPyRobot are intended to be subclassed to add application
specific functionality. In the ``RobotServer`` subclass you can define
operation functions. These can be initiated from clients using the
``RobotClient.run_operation()`` method.

Robot operations should be decorated with ``server.foreground_operation``
or ``server.background_operation`` depending on whether the operation
blocks other robot operations or not. For example, any operation that will
drive the robot is a ``foreground_operation`` but reading information from the
robot can be run in the background.

For example::

    from aspyrobot import RobotServer, RobotClient
    from aspyrobot.server import foreground_operation
    from aspyrobot.exceptions import RobotError

    class SAMRobotServer(RobotServer):
        @foreground_operation
        def mount_sample(self, handle, sample):
            if self.robot.motors_on.value != 1:
                raise RobotError('Motors must be on')
            self.robot.run_foreground_operation('MountSample', sample)

Then to execute the operation::

    >>> robot = RobotClient()
    >>> robot.setup()
    >>> robot.run_operation('mount_sample', 'l A 1')
