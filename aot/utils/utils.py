# coding=utf-8
#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#

import logging
import random
import os
import re
import string
import sys

logger = logging.getLogger("aot.utils")


def append_to_log(log_file, str_append):
    """Write a string to a log file.

    @phase active
    @stability stable
    """
    if os.path.exists:
        w_type = "a"
    else:
        w_type = "w"
    with open(log_file, w_type) as f:
        f.write(str_append)


def is_email(email):
    """Validate that a string is a properly formatted email address.

    @phase active
    @stability stable
    """
    if re.match('[^@]+@[^@]+\.[^@]+', email) is None:
        print("This doesn't appear to be an email address")
        return False
    else:
        return True


def pass_length_min(pw, min_len=8):
    """Validate that a password meets the minimum length requirement.

    @phase active
    @stability stable
    """
    if not len(pw) >= min_len:
        print("The password provided is too short.")
        return False
    else:
        return True


def characters(un):
    """Validate that a username or password contains only alphanumeric characters.

    @phase active
    @stability stable
    """

    if not un.isalnum():
        print("A special character was detected.  Please use only Letters and Numbers.")
        return False
    else:
        return True


def user_length_min(un, min_len=3):
    """Validate that a username meets the minimum length requirement.

    @phase active
    @stability stable
    """

    if not len(un) >= min_len:
        print("This username is too short.")
        return False
    else:
        return True


def user_length_max(un, max_len=64):
    """Validate that a username does not exceed the maximum length.

    @phase active
    @stability stable
    """
    if not len(un) <= max_len:
        print("This username is too long.")
        return False
    else:
        return True


def test_username(un, addl_tests=None, test_defaults=True):
    """Run validation tests on a username and return whether all tests pass.

    @phase active
    @stability stable
    """
    tests = []

    if test_defaults:
        tests += [characters, user_length_min, user_length_max]

    if addl_tests:
        tests += addl_tests

    return validate_string(un, tests)


def test_password(pw, addl_tests=None, test_defaults=True):
    """Run validation tests on a password and return whether all tests pass.

    @phase active
    @stability stable
    """
    tests = []

    if test_defaults:
        tests += [pass_length_min]

    if addl_tests:
        tests += addl_tests

    return validate_string(pw, tests)


def validate_string(a_str, tests):
    """Apply a list of validation functions to a string and return whether all pass.

    @phase active
    @stability stable
    """

    for test in tests:
        if not test(a_str):
            return False
    return True


def query_yes_no(question, default="yes"):
    """Prompt the user with a yes/no question and return their answer.

    @phase active
    @stability stable
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'y' or 'n').\n")


def sort_tuple(tup):
    """Sort a list of tuples by the second item in each tuple.

    @phase active
    @stability stable
    """
    lst = len(tup)
    for i in range(0, lst):
        for j in range(0, lst - i - 1):
            if tup[j][1] > tup[j + 1][1]:
                temp = tup[j]
                tup[j] = tup[j + 1]
                tup[j + 1] = temp
    return tup


def random_alphanumeric(length):
    """Generate a random alphanumeric string of specified length.

    @phase active
    @stability stable
    """
    key = ''
    for i in range(length):
        key += random.choice(string.ascii_letters + string.digits)
    return key
