# Copyright (C) 2008 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import select
import subprocess
import sys

import platform_utils


active = False
pager_process = None
old_stdout = None
old_stderr = None


def RunPager(globalConfig):
    if not os.isatty(0) or not os.isatty(1):
        return
    pager = _SelectPager(globalConfig)
    if pager == "" or pager == "cat":
        return

    if platform_utils.isWindows():
        _PipePager(pager)
    else:
        _ForkPager(pager)


def TerminatePager():
    global pager_process
    if pager_process:
        sys.stdout.flush()
        sys.stderr.flush()
        pager_process.stdin.close()
        pager_process.wait()
        pager_process = None
        # Restore initial stdout/err in case there is more output in this
        # process after shutting down the pager process.
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def _PipePager(pager):
    global pager_process, old_stdout, old_stderr
    assert pager_process is None, "Only one active pager process at a time"
    # Create pager process, piping stdout/err into its stdin.
    try:
        pager_process = subprocess.Popen(
            [pager], stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr
        )
    except FileNotFoundError:
        sys.exit(f'fatal: cannot start pager "{pager}"')
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = pager_process.stdin
    sys.stderr = pager_process.stdin


def _ForkPager(pager):
    global active
    # This process turns into the pager; a child it forks will
    # do the real processing and output back to the pager. This
    # is necessary to keep the pager in control of the tty.
    try:
        r, w = os.pipe()
        pid = os.fork()
        if not pid:
            os.dup2(w, 1)
            os.dup2(w, 2)
            os.close(r)
            os.close(w)
            active = True
            return

        os.dup2(r, 0)
        os.close(r)
        os.close(w)

        _BecomePager(pager)
    except Exception:
        print("fatal: cannot start pager '%s'" % pager, file=sys.stderr)
        sys.exit(255)


def _SelectPager(globalConfig):
    try:
        return os.environ["GIT_PAGER"]
    except KeyError:
        pass

    pager = globalConfig.GetString("core.pager")
    if pager:
        return pager

    try:
        return os.environ["PAGER"]
    except KeyError:
        pass

    return "less"


def _BecomePager(pager):
    # Delaying execution of the pager until we have output
    # ready works around a long-standing bug in popularly
    # available versions of 'less', a better 'more'.
    _a, _b, _c = select.select([0], [], [0])

    # This matches the behavior of git, which sets $LESS to `FRX` if it is not
    # set. See:
    # https://git-scm.com/docs/git-config#Documentation/git-config.txt-corepager
    os.environ.setdefault("LESS", "FRX")

    try:
        os.execvp(pager, [pager])
    except OSError:
        os.execv("/bin/sh", ["sh", "-c", pager])
