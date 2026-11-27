"""Bounded root PTYs, reachable only through the peer-checked controller.

Each shell runs in its own systemd unit so timeout, controller restart and close
terminate the complete process group, including children that detach from bash.
Shell input/output and passwords are never written to logs by this service.
"""
import codecs
import fcntl
import logging
import os
from pathlib import Path
import secrets
import select
import struct
import subprocess
import sys
import termios
import threading
import time
from updates import update, pc

LIFETIME = 900
DISCONNECT_GRACE = 90
BUFFER_SIZE = 262144
log = logging.getLogger('airlink.terminal')


def supported():
    return sys.platform == 'linux' and Path('/etc/airlink/installed').exists()


def resize(fd, cols, rows):
    if type(cols) is not int or type(rows) is not int or not 20 <= cols <= 300 or not 5 <= rows <= 120:
        raise ValueError('Invalid terminal dimensions')
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))


def maintenance_ready():
    # Failed installations remain accessible for recovery. Active work owns this
    # same lock; the shell unit acquires it again for its entire lifetime.
    with pc.maintenance_lock():
        if (update.read(update.ROOT / 'state.json', {}).get('status') == 'queued' or
                update.restart_status()['pending'] or pc.reconcile(locked=True)['status'] in pc.BUSY):
            raise ValueError('An update or restart is pending. Wait before opening the terminal.')


class Session:
    def __init__(self, identity, cols, rows):
        maintenance_ready()
        self.identity = identity
        self.id = secrets.token_hex(24)
        self.unit = 'airlink-web-terminal-' + self.id + '.service'
        self.created = self.touched = time.monotonic()
        self.lock = threading.RLock()
        self.output = ''
        self.offset = 0
        self.sequence = 0
        self.closed = False
        self.reason = None
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.fd, slave = os.openpty()
        try:
            resize(self.fd, cols, rows)
            subprocess.run([
                'systemd-run', '--quiet', '--collect', '--unit=' + self.unit,
                '--property=Type=exec', '--property=RuntimeMaxSec=900',
                '--property=TimeoutStopSec=5', '--property=KillMode=control-group',
                '--property=BindsTo=airlink-controller.service',
                '--property=After=airlink-controller.service',
                '--property=StandardInput=tty', '--property=StandardOutput=tty',
                '--property=StandardError=tty', '--property=TTYPath=' + os.ttyname(slave),
                '--property=WorkingDirectory=/', '--property=UMask=0077',
                '/usr/bin/flock', '--nonblock', '--no-fork', str(update.ROOT / 'lock'),
                '/usr/bin/env', '-i', 'HOME=/root', 'USER=root', 'LOGNAME=root',
                'SHELL=/bin/bash', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                'TERM=xterm-256color', 'LANG=C.UTF-8', 'HISTFILE=/dev/null',
                'PS1=AirLink root \\w # ', '/bin/bash', '--noprofile', '--norc', '-i',
            ], check=True, capture_output=True, timeout=15)
        except Exception:
            os.close(self.fd)
            self._stop_unit()
            raise ValueError('Could not start the system terminal. Review the controller service.') from None
        finally:
            os.close(slave)
        os.set_blocking(self.fd, False)
        log.warning('Root terminal opened for owner %s', identity[0])
        threading.Thread(target=self._watch, daemon=True).start()

    def _stop_unit(self):
        try:
            subprocess.run(['systemctl', 'stop', '--no-block', self.unit],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            log.error('Terminal stop failed; unit runtime limit remains active')

    def close(self, reason='Terminal closed'):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.reason = reason
            os.close(self.fd)
        self._stop_unit()
        log.warning('Root terminal closed for owner %s: %s', self.identity[0], reason)

    def _watch(self):
        while True:
            with self.lock:
                if self.closed:
                    return
                age = time.monotonic() - self.created
                idle = time.monotonic() - self.touched
                if age >= LIFETIME or idle >= DISCONNECT_GRACE:
                    self.close('Session expired' if age >= LIFETIME else 'Browser disconnected')
                    return
                try:
                    readable, _, _ = select.select([self.fd], [], [], 0)
                    if readable:
                        raw = os.read(self.fd, 16384)
                        if not raw:
                            raise OSError('Shell exited')
                        self.output += self.decoder.decode(raw)
                        excess = max(0, len(self.output) - BUFFER_SIZE)
                        self.output = self.output[excess:]
                        self.offset += excess
                except OSError:
                    self.close('Shell exited')
                    return
            time.sleep(.02)

    def exchange(self, payload):
        with self.lock:
            cursor, sequence, data = payload.get('cursor'), payload.get('sequence'), payload.get('data', '')
            if (type(cursor) is not int or not 0 <= cursor <= self.offset + len(self.output) or
                    type(sequence) is not int or sequence < 0 or not isinstance(data, str) or len(data) > 4096):
                raise ValueError('Invalid terminal exchange')
            if not self.closed:
                resize(self.fd, payload.get('cols'), payload.get('rows'))
                # Replayed exchanges acknowledge the same input without executing twice.
                if data and sequence == self.sequence + 1:
                    raw = data.encode('utf-8')
                    deadline = time.monotonic() + 2
                    while raw:
                        try:
                            count = os.write(self.fd, raw)
                            raw = raw[count:]
                        except BlockingIOError:
                            if time.monotonic() >= deadline:
                                self.close('Terminal input stalled; reconnect before continuing')
                                raise ValueError(self.reason)
                            time.sleep(.01)
                        except OSError:
                            self.close('Shell exited')
                            break
                    self.sequence = sequence
                elif sequence != self.sequence:
                    raise ValueError('Terminal input sequence changed; reconnect')
                self.touched = time.monotonic()
            start = max(cursor, self.offset)
            output = self.output[start - self.offset:start - self.offset + 16384]
            finished = self.closed and start + len(output) == self.offset + len(self.output)
            return {'output': output,
                    'cursor': start + len(output), 'truncated': cursor < self.offset,
                    'closed': finished, 'reason': self.reason if finished else None}


class TerminalService:
    def __init__(self):
        self.lock = threading.Lock()
        self.session = None

    def action(self, name, payload):
        if name == 'status':
            return {'supported': supported(), 'lifetime_seconds': LIFETIME,
                    'disconnect_seconds': DISCONNECT_GRACE,
                    'reason': None if supported() else 'The system terminal runs on the installed AirLink Linux PC. It is unavailable in preview.'}
        if not supported() or os.geteuid() != 0:
            raise ValueError('The system terminal requires the installed AirLink Linux PC')
        identity = (payload.get('owner_id'), payload.get('login_session'))
        if not all(isinstance(value, str) and value for value in identity):
            raise ValueError('Terminal owner session required')
        with self.lock:
            if name == 'open':
                if self.session and not self.session.closed:
                    raise ValueError('A system terminal is already open. Close it or wait 90 seconds after disconnecting.')
                self.session = Session(identity, payload.get('cols'), payload.get('rows'))
                return {'session_id': self.session.id, 'lifetime_seconds': LIFETIME}
            session = self.session
            if (not session or identity != session.identity or
                    payload.get('session_id') != session.id):
                raise ValueError('Terminal session expired or belongs to another login')
            if name == 'close':
                session.close()
                return {'closed': True}
            if name == 'exchange':
                return session.exchange(payload)
            raise ValueError('Unknown terminal action')


service = TerminalService()
