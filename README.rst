=======
mjscore
=======

mjscore is a scoring system for Mech Warfare (http://mech-warfare.com)
style competitions between scale size legged robots.

* GitHub https://github.com/mjbots/mjscore
* Free hardware and software: Apache 2.0 License

Overview
========

The scoring system consists of piezo panels which are affixed around
the robot, and a transponder which powers the panels and relays
scoring information to a central station.

Panels
======

Each panel consists of:

* A laser cut front and back plate made of 1/16" Delrin.
* A piezo sensor affixed to the back side of the front plate with contact cement.
* A conditioning board, consisting of an ATTiny85 which samples the
  piezo, and emits scoring hits and debugging information.

There is a full sized (3.5"x3.5") configuration, and a half sized
configuration.  For the half-sized configuration, each portion has a
separate conditioning board, which should be daisy chained together to
drive a transponder.


Transponder
===========

The mjscore panels are designed to inter-operate with any revision of
the official Mech Warfare transponders, or for instance, the RTEAM
version at: https://github.com/bloftin/rbots/

Base Station
============

For the RTEAM and official Mech Warfare transponders, the base station
can consist of an XBee explorer, such as this pair from SparkFun:

* https://www.sparkfun.com/products/11812
* https://www.sparkfun.com/products/8710
