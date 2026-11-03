import asyncio
import pytest
from airlink import routeros_native as ros


def test_word_encoding_round_trip_all_length_prefixes():
    async def check():
        for length in (0, 1, 127, 128, 16383, 16384, 65536):
            connection = ros.Connection('unused', {})
            connection.reader = asyncio.StreamReader()
            connection.reader.feed_data(ros.word('a' * length))
            assert await connection.read_word() == 'a' * length
        connection.reader.feed_data(b'\xf0\x00\x00\x00\x01x')
        assert await connection.read_word() == 'x'
    asyncio.run(check())


def test_sentence_auth_and_data_and_trap_response(monkeypatch):
    async def check():
        reader = asyncio.StreamReader()
        responses = [ ['!done'], ['!re', '=.id=*1', '=name=ether1'], ['!done'],
                      ['!trap', '=message=private-device-error'], ['!done'] ]
        for sentence in responses:
            reader.feed_data(b''.join(ros.word(x) for x in sentence) + b'\0')
        class Writer:
            calls = []
            def write(self, data): self.calls.append(data)
            async def drain(self): pass
            def close(self): pass
            async def wait_closed(self): pass
        writer = Writer()
        async def open_connection(*a, **kw):
            assert a == ('10.2.3.4', 8728)
            return reader, writer
        monkeypatch.setattr(asyncio, 'open_connection', open_connection)
        async with ros.Connection('10.2.3.4', {'api_username': 'user', 'api_password': 'secret'}) as connection:
            result = await connection.read('interface/ethernet?.proplist=.id,name')
            assert result == [{'.id': '*1', 'name': 'ether1'}]
            assert await connection.read('unsupported') is None
        assert b'/login' in writer.calls[0]
        assert b'=.proplist=.id,name' in writer.calls[1]
        assert b'/interface/ethernet/print' in writer.calls[1]
    asyncio.run(check())


def test_oversized_or_reserved_words_are_rejected():
    async def check(value):
        connection = ros.Connection('unused', {})
        connection.reader = asyncio.StreamReader()
        connection.reader.feed_data(value)
        with pytest.raises(ros.APIError):
            await connection.read_word()
    asyncio.run(check(b'\xf8'))
    asyncio.run(check(b'\xf0\x00\x20\x00\x00'))
