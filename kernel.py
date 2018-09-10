"""
Jupyter kernel for GemStone/S 64 Bit Topaz command line
"""
import os as os
from ipykernel.kernelbase import Kernel
from pexpect import (spawn, replwrap, EOF)
from subprocess import check_output
import re
import signal
from .images import (
    extract_image_filenames, display_data_for_image, image_setup_cmd
)

__version__ = '1.0.0'
version_pat = re.compile(r'version (\d+(\.\d+)+)')


class TopazKernel(Kernel):
    implementation = 'topaz_kernel'
    implementation_version = __version__

    @property
    def language_version(self):
        m = version_pat.search(self.banner)
        return m.group(1)

    _banner = None

    @property
    def banner(self):
        if self._banner is None:
            self._banner = check_output(['topaz', '-v']).decode('utf-8')
        return self._banner

    language_info = {'name': 'topaz',
                     'codemirror_mode': 'shell',
                     'mimetype': 'text/x-sh',
                     'file_extension': '.tpz'}

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        self._start_topaz()

    def _start_topaz(self):
        # Signal handlers are inherited by forked processes, and we can't easily
        # reset it from the subprocess. Since kernelapp ignores SIGINT except in
        # message handlers, we need to temporarily reset the SIGINT handler here
        # so that topaz and its children are interruptible.
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            child = spawn(command="topaz", args=['-il'], timeout=1, echo=True, encoding='utf-8')
            self.topazwrapper = replwrap.REPLWrapper(child,
                                                     orig_prompt='topaz> ',
                                                     prompt_change='set user DataCurator pass swordfish gems gs64stone\nlogin',
                                                     new_prompt='topaz 1> ')
        finally:
            signal.signal(signal.SIGINT, sig)

        # Register Topaz function to write image data to temporary file
        # self.topazwrapper.run_command(image_setup_cmd)

    def do_apply(self, content, bufs, msg_id, reply_metadata):
        pass

    def do_clear(self):
        pass

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):

        input = code
        # check for an empty line
        if not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

        # we disallow several commands
        if code.lower().startswith(('ed', 'exi', 'log', 'pa', 'q', 'sh', 'sp')):
            stream_content = {'name': 'stdout', 'text': 'Unauthorized command!'}
            self.send_response(self.iopub_socket, 'stream', stream_content)
            return {'status': 'abort', 'execution_count': self.execution_count,
                    'payload': [''], 'user_expressions': {}}

        # multiline commands need to be handled specially
        if code.lower().startswith(('doi', 'pr', 'ru')):
            lines = code.splitlines()
            if lines[-1] == '%':
                lines.pop()
            for line in lines:
                self.topazwrapper.child.sendline(line)
            code = '%'

        # EXEC command is even more special
        if code.lower().startswith('exe'):
            lines = code.splitlines()
            if len(lines) > 1 or not code.rstrip()[-1] == '%':
                if lines[-1] == '%':
                    lines.pop()
                for line in lines:
                    self.topazwrapper.child.sendline(line)
                code = '%'

        interrupted = False
        try:
            # noinspection PyTypeChecker
            output = self.topazwrapper.run_command(code.rstrip(), timeout=None)
        except KeyboardInterrupt:
            self.topazwrapper.child.sendintr()
            interrupted = True
            self.topazwrapper._expect_prompt()
            output = self.topazwrapper.child.before
        except EOF:
            output = self.topazwrapper.child.before + 'Restarting Topaz'
            self._start_topaz()

        if not silent:
            image_filenames, output = extract_image_filenames(output)

            # Send standard output
            if output.startswith(input):
                output = output[len(input) + 2:-1]
            stream_content = {'name': 'stdout', 'text': output}
            self.send_response(self.iopub_socket, 'stream', stream_content)

            # Send images, if any
            for filename in image_filenames:
                try:
                    data = display_data_for_image(filename)
                except ValueError as e:
                    message = {'name': 'stdout', 'text': str(e)}
                    self.send_response(self.iopub_socket, 'stream', message)
                else:
                    self.send_response(self.iopub_socket, 'display_data', data)

        if interrupted:
            return {'status': 'abort', 'execution_count': self.execution_count}

        # noinspection PyBroadException
        try:
            exitcode = 0	# int(self.topazwrapper.run_command('echo $?').rstrip())
        except Exception:
            exitcode = 1

        if exitcode:
            error_content = {'execution_count': self.execution_count,
                             'ename': '', 'evalue': str(exitcode), 'traceback': []}

            self.send_response(self.iopub_socket, 'error', error_content)
            error_content['status'] = 'error'
            return error_content
        else:
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

    def do_complete(self, code, cursor_pos):
        code = code[:cursor_pos]
        default = {'matches': [], 'cursor_start': 0,
                   'cursor_end': cursor_pos, 'metadata': dict(),
                   'status': 'ok'}

        if not code or code[-1] == ' ':
            return default

        tokens = code.replace(';', ' ').split()
        if not tokens:
            return default

        matches = []
        token = tokens[-1]
        start = cursor_pos - len(token)

        if token[0] == '$':
            # complete variables
            cmd = 'compgen -A arrayvar -A export -A variable %s' % token[1:]  # strip leading $
            output = self.topazwrapper.run_command(cmd).rstrip()
            completions = set(output.split())
            # append matches including leading $
            matches.extend(['$'+c for c in completions])
        else:
            # complete functions and builtins
            cmd = 'compgen -cdfa %s' % token
            output = self.topazwrapper.run_command(cmd).rstrip()
            matches.extend(output.split())

        if not matches:
            return default
        matches = [m for m in matches if m.startswith(token)]

        return {'matches': sorted(matches), 'cursor_start': start,
                'cursor_end': cursor_pos, 'metadata': dict(),
                'status': 'ok'}
