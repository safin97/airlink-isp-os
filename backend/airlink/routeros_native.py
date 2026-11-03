"""Bounded RouterOS sentence API transport for RouterOS 6 and 7."""
import asyncio
import hashlib
import ssl
from urllib.parse import parse_qs


class APIError(Exception):
    pass


def word(value):
    data = value.encode('utf-8')
    size = len(data)
    if size < 0x80:
        prefix = bytes([size])
    elif size < 0x4000:
        prefix = (size | 0x8000).to_bytes(2, 'big')
    elif size < 0x200000:
        prefix = (size | 0xC00000).to_bytes(3, 'big')
    else:
        raise APIError('API word is too large')
    return prefix + data


class Connection:
    def __init__(self, address, config):
        self.address, self.config = address, config
        self.reader = self.writer = None

    async def __aenter__(self):
        secure = self.config.get('transport') == 'routeros_tls'
        context = ssl.create_default_context() if secure else None
        if context and not self.config.get('verify_tls', True):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(
            self.address, self.config.get('port') or (8729 if secure else 8728), ssl=context), 4)
        try:
            result = await self.command('/login', {
                'name': self.config['api_username'], 'password': self.config['api_password']})
            challenge = result[0].get('ret') if result else None
            if challenge:
                digest = hashlib.md5(b'\0' + self.config['api_password'].encode() + bytes.fromhex(challenge)).hexdigest()
                await self.command('/login', {'name': self.config['api_username'], 'response': '00' + digest})
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        if self.writer:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass

    async def read_word(self):
        first = (await self.reader.readexactly(1))[0]
        if first < 0x80:
            size = first
        elif first < 0xC0:
            size = ((first & 0x3F) << 8) | int.from_bytes(await self.reader.readexactly(1), 'big')
        elif first < 0xE0:
            size = ((first & 0x1F) << 16) | int.from_bytes(await self.reader.readexactly(2), 'big')
        elif first < 0xF0:
            size = ((first & 0x0F) << 24) | int.from_bytes(await self.reader.readexactly(3), 'big')
        elif first == 0xF0:
            size = int.from_bytes(await self.reader.readexactly(4), 'big')
        else:
            raise APIError('Unsupported API word')
        if size > 1024 * 1024:
            raise APIError('Device response is too large')
        return (await self.reader.readexactly(size)).decode('utf-8', errors='replace')

    async def command(self, path, attributes=None):
        async def exchange():
            self.writer.write(b''.join(word(v) for v in [path] +
                ['=' + key + '=' + str(value) for key, value in (attributes or {}).items()]) + b'\0')
            await self.writer.drain()
            result, failed, total = [], False, 0
            while True:
                sentence = []
                while True:
                    item = await self.read_word()
                    total += len(item) + 1
                    if total > 1024 * 1024:
                        raise APIError('Device response is too large')
                    if not item:
                        break
                    sentence.append(item)
                if not sentence:
                    continue
                kind = sentence[0]
                values = dict(item[1:].split('=', 1) for item in sentence[1:]
                              if item.startswith('=') and '=' in item[1:])
                if kind in ('!trap', '!fatal'):
                    if path == '/login':
                        raise PermissionError('Device login rejected')
                    if kind == '!fatal':
                        raise APIError('Device API disconnected')
                    failed = True
                if kind == '!re':
                    result.append(values)
                if kind == '!done':
                    if failed:
                        raise APIError('Device command is unavailable or permission was denied')
                    return result or ([values] if values else [])
        return await asyncio.wait_for(exchange(), 5)

    async def read(self, path, payload=None):
        menu, _, query = path.partition('?')
        attributes = {k: v[0] for k, v in parse_qs(query).items()}
        try:
            return await self.command('/' + menu + ('/print' if payload is None else ''),
                                      attributes if payload is None else payload)
        except APIError:
            return None
