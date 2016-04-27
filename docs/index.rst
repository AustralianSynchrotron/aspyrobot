.. ASPyRobot documentation master file, created by
   sphinx-quickstart on Wed Apr 27 15:31:10 2016.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

ASPyRobot
=========

ASPyRobot provides a Python interface to control EPSON robots. The robot
controller must be connected to a RobotEpsonIP EPICS IOC.

Basic usage::

    >>> from aspyrobot import RobotServer, RobotClient, Robot
    >>> server = RobotServer(Robot('SR08ID01ROB01:'))
    >>> server.setup()
    >>> robot = RobotClient()
    >>> robot.setup()
    >>> robot.model
    'G6-553S-II'
    >>> robot.closest_point
    16

Contents
========

.. toctree::
   :maxdepth: 2

   guide
   api

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

