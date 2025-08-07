AoT
======

환경 제어 시스템

최신 버전: 0.0.1

AoT is open source software for the Raspberry Pi that couples inputs and outputs in interesting ways to sense and manipulate the environment.
This file has been modified by AoT from the original Mycodo version.

|Build Status| |Codacy Badge| |Translation Badge| |DOI|

.. contents:: Table of Contents
   :depth: 1

Quick Install
-------------

Prerequisites: Debian-based Linux operating system (apt).

Recommended: Single board computer (SBC) with General-Purpose Input-Output (GPIO) pins.

Install Command:

.. code:: bash

    curl -L https://aot-inc.github.io/AoT/install | bash


See the `Install AoT <#install-aot>`__ section for more details.

Support
-------

Documentation
~~~~~~~~~~~~~

`AoT Manual <https://aot-inc.github.io/AoT>`__

`AoT API <https://aot-inc.github.io/AoT/aot-api.html>`__ (Version: v1)

`AoT Wiki <https://github.com/aot-inc/AoT/wiki>`__

`AoT Custom Module Repository <https://github.com/aot-inc/AoT-custom>`__

Discussion
~~~~~~~~~~

`AoT Issues (Bug Reports/Feature Requests) <https://github.com/aot-inc/AoT/issues>`__

`AoT Forum <https://forum.radicaldiy.com>`__

`AoT Discord <https://discord.gg/kmDNky4ZHZ>`__

Bug in the AoT Software
~~~~~~~~~~~~~~~~~~~~~~~~~~

If you believe there is a bug in the AoT software, first search through the github `Issues <https://github.com/aot-inc/AoT/issues>`__ and see if your issue has already recently been discussed or resolved. If your issue is novel or significantly more recent than a similar one, you should create a `New Issue <https://github.com/aot-inc/AoT/issues/new>`__. When creating a new issue, make sure to read all information in the issue template and follow the instructions. Replace the template text with the information being requested (e.g. "step 1" under "Steps to Reproduce the issue" should be replaced with the actual steps to reproduce the issue). The more information you provide, the easier it is to reproduce and diagnose the issue. If the issue is not able to reproduced because not enough information is provided, it may delay or prevent solving the issue.

Donate
------

I have always made AoT free and I don't intend on changing that. However, if you find AoT useful and would like to support its continued development, please consider becoming a sponsor at `github.com/sponsors/aot-inc <https://github.com/sponsors/aot-inc>`__ or donate at `kylegabriel.com/donate <https://kylegabriel.com/donate>`__.

Features
--------

-  `Inputs <https://aot-inc.github.io/AoT/Inputs/>`__ that record measurements from sensors, GPIO pin states, analog-to-digital converters, and more (or create your own `Custom Inputs <https://aot-inc.github.io/AoT/Inputs/#custom-inputs>`__). See all `Supported Inputs <https://aot-inc.github.io/AoT/Supported-Inputs-By-Measurement/>`__.
-  `Outputs <https://aot-inc.github.io/AoT/Outputs/>`__ that perform actions such as switching GPIO pins high/low, generating PWM signals, executing shell scripts and Python code, and more (or create your own `Custom Outputs <https://aot-inc.github.io/AoT/Outputs/#custom-outputs>`__). See all `Supported Outputs <https://aot-inc.github.io/AoT/Supported-Outputs/>`__.
-  `Functions <https://aot-inc.github.io/AoT/Functions/>`__ that perform tasks, such as coupling Inputs and Outputs in interesting ways, such as `PID <https://aot-inc.github.io/AoT/Functions/#pid-controller>`__, `Conditional <https://aot-inc.github.io/AoT/Functions/#conditional>`__, `Trigger <https://aot-inc.github.io/AoT/Functions/#trigger>`__, to name a few (or create your own `Custom Functions <https://aot-inc.github.io/AoT/Functions/#custom-functions>`__). See all `Supported Functions <https://aot-inc.github.io/AoT/Supported-Functions/>`__.
-  `Web Interface <https://aot-inc.github.io/AoT/About/#web-interface>`__ for securely accessing AoT using a web browser on your local network or anywhere in the world with an internet connection, to view and configure the system, which includes several light and dark themes.
-  `Dashboards <https://aot-inc.github.io/AoT/Data-Viewing/#dashboard>`__ that display configurable widgets, including interactive live and historical graphs, gauges, output state indicators, measurements, and more (or create your own `Custom Widgets <https://aot-inc.github.io/AoT/Widgets/#custom-widgets>`__). See all `Supported Widgets <https://aot-inc.github.io/AoT/Supported-Widgets/>`__.
-  `Alert Notifications <https://aot-inc.github.io/AoT/Alerts/>`__ to send emails when measurements reach or exceed user-specified thresholds, important for knowing immediately when issues arise.
-  `Setpoint Tracking <https://aot-inc.github.io/AoT/Methods/>`__ for changing a PID controller setpoint over time, for use with things like terrariums, reflow ovens, thermal cyclers, sous-vide cooking, and more.
-  `Notes <https://aot-inc.github.io/AoT/Notes/>`__ to record events, alerts, and other important points in time, which can be overlaid on graphs to visualize events with your measurement data.
-  `Cameras <https://aot-inc.github.io/AoT/Camera/>`__ for remote live streaming, image capture, and time-lapse photography.
-  `Energy Usage Measurement <https://aot-inc.github.io/AoT/Energy-Usage/>`__ for calculating and tracking power consumption and cost over time.
-  `Upgrade System <https://aot-inc.github.io/AoT/Upgrade-Backup-Restore/>`__ to easily upgrade the AoT system to the latest release to get the newest features or restore to a previously-backed up version.
-  `Translations <https://aot-inc.github.io/AoT/Translations/>`__ that enable the web interface to be presented in different `Languages <https://github.com/aot-inc/AoT#features>`__.

.. image:: https://kylegabriel.com/projects/wp-content/uploads/sites/3/2020/06/Screenshot_2020-04-25-hydra-Default-Dashboard-AoT-8-4-0-dashboard_2.png
   :target: https://kylegabriel.com/projects/wp-content/uploads/sites/3/2020/06/Screenshot_2020-04-25-hydra-Default-Dashboard-AoT-8-4-0-dashboard_2.png

Figure: `Automated Hydroponic System Build <https://kylegabriel.com/projects/2020/06/automated-hydroponic-system-build.html>`__

--------------

Uses
----

Originally developed to cultivate edible mushrooms, AoT has evolved to do much more. Here are a few things that have been done with AoT:


Featured Projects
~~~~~~~~~~~~~~~~~

.. image:: https://kylegabriel.com/projects/wp-content/uploads/sites/3/2021/09/MushroomCultivation_512x288.jpg
   :target: https://www.youtube.com/watch?v=z41Wy5ZF4O8

.. image:: https://kylegabriel.com/projects/wp-content/uploads/sites/3/2020/07/VID_PROJ_HYDRO_512x288.jpg
   :target: https://www.youtube.com/watch?v=nyqykZK2Ev4

Projects by Others
~~~~~~~~~~~~~~~~~~

-  Maintaining aquatic systems (e.g. fish, hydroponic, aquaponic)
-  Maintaining terrarium, herpetarium, and vivarium environments
-  Incubating young animals and eggs
-  Aging cheese
-  Dry-aging, curing, and smoking meat (`Link 1 <http://www.charcuterie-worst.nl/forum/index.php/topic,425.0.html>`__ (`Archive <http://archive.is/NHKqp>`__), `Link 2 <https://www.floriske.nl/wordpress/2019/06/meat-curing-cabinet/>`__ (`Archive <https://archive.ph/57ouJ>`__))
-  Fermenting beer, food, and tobacco
-  Controlling reflow ovens
-  Culturing microorganisms
-  `Treating agricultural waste water <https://projects.sare.org/project-reports/gne17-158/>`__ (`Archive <http://archive.is/enJQs>`__, `Publication <https://pubs.acs.org/doi/pdf/10.1021/acsestwater.0c00234>`__)
-  ...and more

`Let me know <https://kylegabriel.com/contact/>`__ how you use AoT and I may include it on this list.

Screenshots
-----------

Visit the `Screenshots <https://github.com/aot-inc/AoT/wiki/Screenshots>`__ page of the Wiki.

Install AoT
--------------

Prerequisites
~~~~~~~~~~~~~

Required:

-  Debian-based operating system
-  An active internet connection

Recommended:

-  `Raspberry Pi <https://www.raspberrypi.org>`__ single-board computer: 3, 4, or 5 (Zero, 1, and 2 are no longer recommended)
-  `Raspberry Pi Operating System <https://www.raspberrypi.com/software/>`__ flashed to a micro SD card or SSD

AoT has been tested to work with Raspberry Pi OS 12 (Bookworm release), Lite and Desktop, 32-bit and 64-bit.

Install Command
~~~~~~~~~~~~~~~

Once you have the Raspberry Pi booted, log in and run the following command in a terminal to initiate the AoT install to /opt/AoT:

.. code:: bash

    curl -L https://aot-inc.github.io/AoT/install | bash


Install Notes
~~~~~~~~~~~~~

Make sure the install script finishes without errors. A log of the output will be created at ``/opt/AoT/install/setup.log``.

If the install is successful, the web user interface should be accessible by navigating a web browser to ``https://127.0.0.1/``, replacing ``127.0.0.1`` with the IP address of the computer you installed on. Upon your first visit, you will be prompted to create an admin user before being redirected to the login page. Once logged in, check that the time is correct at the top left of the page. Incorrect time can cause a number of issues with measurement storage and retrieval in a time-series database. Also ensure the host name and version number at the top left of the page is green, indicating the daemon is running. If it's red, it indicates the daemon is inactive or unresponsive. Last, ensure any java-blocking plugins of your browser are disabled for all parts of the web interface to function properly.

If you receive an error during the install that you believe is preventing your system from operating, please `create an issue <https://github.com/aot-inc/AoT/issues>`__ with the install log attached. If you would first like to attempt to diagnose the issue yourself, see `Diagnosing Issues <#diagnosing-issues>`__.

A minimal set of anonymous usage statistics are collected to help improve development. No identifying information is saved from the information that is collected and it is only used to improve AoT. No one other than the development team will have access to this information and it will never be sold. The data collected is mainly what and how many features are used, and other similar information. The data that's collected can be viewed from the 'View collected statistics' link in the ``Settings -> General`` page. There is an opt out option on the General Settings page if you want to turn this functionality off.

Measurement Database
~~~~~~~~~~~~~~~~~~~~

AoT currently supports InfluxDB as the time-series database used to store measurements. Both versions 1.x (for 32-bit systems) and 2.x (for 64-bit systems) are supported. During the install, you will be prompted to install 1.x, 2.x, or none (if you wish to set up your own, either locally or remotely). The settings for the database can be reconfigured after install.

Docker
~~~~~~

Docker support is experimental, but if you want to try it, read the docker `README.md <https://github.com/aot-inc/AoT/blob/master/docker/README.md>`__. There is also a `Docker Issue (#637) <https://github.com/aot-inc/AoT/issues/637>`__ on github for those that wish to help with development.

REST API
--------

The latest API documentation can be found here: `API Information <https://aot-inc.github.io/AoT/API/>`__ and `API Endpoint Documentation <https://aot-inc.github.io/AoT/aot-api.html>`__.

About PID Control
-----------------

A `proportional–integral–derivative (PID) controller <https://en.wikipedia.org/wiki/PID_controller>`__ is a control loop feedback mechanism used throughout industry for controlling systems. It efficiently brings a measurable condition, such as temperature, to a desired state (setpoint). A well-tuned PID controller can raise to a setpoint quickly, have minimal overshoot, and maintain the setpoint with little oscillation.

.. figure:: docs/images/PID-Animation.gif
   :alt: PID Animation


|AoT|

The top graph visualizes the regulation of temperature. The red line is the desired temperature (setpoint) that has been configured to change over the course of each day. The blue line is the actual recorded temperature. The green vertical bars represent how long a heater has been activated for every 20-second period. This regulation was achieved with minimal tuning, and already displays a very minimal deviation from the setpoint (±0.5° Celsius). Further tuning would reduce this variability further.

See the `PID Controller <https://aot-inc.github.io/AoT/Functions/#pid-controller>`__ and `PID Tuning <https://aot-inc.github.io/AoT/Functions/#pid-tuning>`__ sections of the manual for more information.

Supported Inputs and Outputs
----------------------------

All supported Inputs, Outputs, and other devices can be found under the `Supported Devices <https://aot-inc.github.io/AoT/Supported-Inputs-By-Measurement/>`__ section of the manual.

Custom Inputs, Outputs, Functions, Actions, and Widgets
-------------------------------------------------------

AoT supports importing custom Input, Output, Function, Action, and Widget modules. you can find more information about each in the manual under `Custom Inputs <https://aot-inc.github.io/AoT/Inputs/#custom-inputs>`__, `Custom Outputs <https://aot-inc.github.io/AoT/Outputs/#custom-outputs>`__, `Custom Functions <https://aot-inc.github.io/AoT/Functions/#custom-functions>`__, `Custom Actions <https://aot-inc.github.io/AoT/Functions/#custom-actions>`__, and `Custom Widgets <https://aot-inc.github.io/AoT/Data-Viewing/#custom-widgets>`__.

If you would like to add to the list of supported Inputs, Outputs, Functions, Actions, and Widgets, submit a pull request with the module you created or start a `New Issue <https://github.com/aot-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=>`__.

Additionally, I have another github repository devoted to custom modules that do not necessarily fit with the built-in set and are not included by default with AoT, but can be imported. These can be found at `aot-inc/AoT-custom <https://github.com/aot-inc/AoT-custom>`__.

Links
-----

Thanks for using and supporting AoT, however depending where you found this documentation, you may not have the latest version or it may have been altered, if not obtained through an official distribution site. You should be able to find the latest version on github.

https://github.com/aot-inc/AoT

https://KyleGabriel.com

https://RadicalDIY.com

License
-------

See `License.txt <https://github.com/aot-inc/AoT/blob/master/LICENSE.txt>`__

AoT is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

AoT is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the `GNU General Public License <http://www.gnu.org/licenses/gpl-3.0.en.html>`__ for more details.

A full copy of the GNU General Public License can be found at http://www.gnu.org/licenses/gpl-3.0.en.html

This software includes third party open source software components. Please see individual files for license information, if applicable.



Thanks
------

AoT는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로 대한민국 실정에 맞게 수정된 버전입니다.
또한 다음의 다양한 오픈소스 라이브러리를 활용하기 때문에 사용할 수 있습니다.
이 프로젝트를 가능하게 해주신 모든 분들께 감사드립니다.

-  `Alembic <https://alembic.sqlalchemy.org>`__
-  `Argparse <https://pypi.org/project/argparse>`__
-  `Bcrypt <https://pypi.org/project/bcrypt>`__
-  `Bootstrap <https://getbootstrap.com>`__
-  `Daemonize <https://pypi.org/project/daemonize>`__
-  `Date Range Picker <https://github.com/dangrossman/daterangepicker>`__
-  `Distro <https://pypi.org/project/distro>`__
-  `Email_Validator <https://pypi.org/project/email_validator>`__
-  `Filelock <https://pypi.org/project/filelock>`__
-  `Flask <https://pypi.org/project/flask>`__
-  `Flask_Accept <https://pypi.org/project/flask_accept>`__
-  `Flask_Babel <https://pypi.org/project/flask_babel>`__
-  `Flask_Compress <https://pypi.org/project/flask_compress>`__
-  `Flask_Limiter <https://pypi.org/project/flask_limiter>`__
-  `Flask_Login <https://pypi.org/project/flask_login>`__
-  `Flask_Marshmallow <https://pypi.org/project/flask_marshmallow>`__
-  `Flask_Profiler <https://github.com/muatik/flask-profiler>`__
-  `Flask_RESTX <https://pypi.org/project/flask_restx>`__
-  `Flask_Session <https://pypi.org/project/flask_session>`__
-  `Flask_SQLAlchemy <https://pypi.org/project/flask_sqlalchemy>`__
-  `Flask_Talisman <https://pypi.org/project/flask_talisman>`__
-  `Flask_WTF <https://pypi.org/project/flask_wtf>`__
-  `FontAwesome <https://fontawesome.com>`__
-  `Geocoder <https://pypi.org/project/geocoder>`__
-  `gridstack.js <https://github.com/gridstack/gridstack.js>`__
-  `Gunicorn <https://gunicorn.org>`__
-  `Highcharts <https://www.highcharts.com>`__
-  `importlib_metadata <https://github.com/python/importlib_metadata>`__
-  `InfluxDB <https://github.com/influxdata/influxdb>`__
-  `influxdb <https://github.com/influxdata/influxdb-python>`__
-  `influxdb_client <https://github.com/influxdata/influxdb-client-python>`__
-  `jQuery <https://jquery.com>`__
-  `Marshmallow_SQLAlchemy <https://pypi.org/project/marshmallow_sqlalchemy>`__
-  `Pyro5 <https://github.com/irmen/Pyro5>`__
-  `SQLAlchemy <https://www.sqlalchemy.org>`__
-  `SQLite <https://www.sqlite.org>`__
-  `toastr <https://github.com/CodeSeven/toastr>`__
-  `Werkzeug <https://palletsprojects.com/p/werkzeug/>`__
-  `WTForms <https://pypi.org/project/wtforms>`__

