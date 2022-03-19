# Copyright (c) 2022 PaddlePaddle Authors. All Rights Reserved.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import OrderedDict
from paddle.distributed.run.utils.process_context import ProcessContext

from .status import Status

import os, copy, sys
import time


class Container(object):
    '''
    TODO(kuizhiqing) A container can be run by process/thread or just a callable function
    '''

    def __init__(self, entrypoint=[], rank=-1, env={}):
        self._entrypoint = entrypoint
        self._rank = rank
        self._out = None
        self._err = None
        self._env = env
        self._proc = None

        self._retry: int = 3
        self._grace_period = 10

        self._log_handler = None

    @property
    def entrypoint(self):
        return self._entrypoint

    @entrypoint.setter
    def entrypoint(self, entry):
        self._entrypoint = entry

    @property
    def rank(self):
        return self._rank

    @rank.setter
    def rank(self, r):
        self._rank = r

    @property
    def outfile(self):
        return self._out

    @outfile.setter
    def outfile(self, out):
        self._out = out

    @property
    def errfile(self):
        return self._err

    @errfile.setter
    def errfile(self, err):
        self._err = err

    def update_env(self, env={}, **kwargs):
        env = {k: v for k, v in env.items() if isinstance(v, str)}
        self._env.update(env)

        kwargs = {k: v for k, v in kwargs.items() if isinstance(v, str)}
        self._env.update(kwargs)

    def _get_fd(self, pth):
        if not pth:
            return None

        try:
            d = os.path.dirname(pth)
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            return open(pth, 'w')
        except:
            return None

    def start(self, timeout=-1):
        end = time.time() + timeout

        if self._proc and self._proc.alive():
            return True

        self._stdout = self._get_fd(self._out) or sys.stdout
        if self._out == self._err:
            self._stderr = self._stdout
        elif self._err:
            self._stderr = self._get_fd(self._err) or sys.stderr

        self._proc = ProcessContext(
            self._entrypoint, env=self._env, out=self._stdout, err=self._stderr)
        self._proc.start()

        while timeout > 0 and time.time() < end:
            if self._proc.alive():
                time.sleep(0.1)
                continue
            if self._proc.exit_code() == 0:
                return True
            return False

    def terminate(self, force=False):
        if self._log_handler:
            self._log_handler.close()
            self._log_handler = None

        if self._proc and self._proc.alive():
            return self._proc.terminate(force)

    def wait(self, timeout=None):
        self._proc.wait(timeout)

    def exit_code(self):
        return self._proc.exit_code() if self._proc else -1

    def status(self):
        if not self._proc:
            return Status.UNINIT
        if self._proc.alive():
            return Status.RUNNING
        elif self._proc.exit_code() == 0:
            return Status.COMPLETED
        else:
            return Status.FAILED

    def __str__(self):
        return 'Container rank {} status {} cmd {} code {} log {} \nenv {}'.format(
            self._rank,
            self.status(),
            self._entrypoint,
            self.exit_code(),
            self.errfile,
            self._env, )

    def logs(self, fn=None, offset=0, whence=1, lines=1000):
        if not self._log_handler:
            self._log_handler = open(self._out)

        if fn is None:
            fn = sys.stdout

        self._log_handler.seek(offset, whence)

        try:
            idx = 0
            for line in self._log_handler:
                fn.write(line)
                idx += 1
                if idx > lines:
                    break
        finally:
            return self._log_handler.tell()

    def tail(self, length=3000):
        if not self._log_handler:
            self._log_handler = open(self._out)

        self._log_handler.seek(0, 2)
        ed = self._log_handler.tell()

        if ed > length:
            self.logs(offset=ed - length, whence=0)
        else:
            self.logs(offset=0, whence=0)
