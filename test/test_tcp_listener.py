from flockwave.connections import TCPListenerConnection

from trio import Event, open_tcp_stream


async def test_tcp_listener_connection(nursery):
    async def _sender(port, event):
        stream = await open_tcp_stream("localhost", port)
        async with stream:
            await stream.send_all(b"hello world")
            await stream.send_eof()

            response = []
            while True:
                chunk = await stream.receive_some()
                if chunk:
                    response.append(chunk)
                else:
                    break

            assert b"".join(response) == b"hello world"
        event.set()

    async def _receiver(stream):
        while True:
            data = await stream.read()
            if data:
                await stream.write(data)
            else:
                break

    async def _listener(task_status):
        listener = TCPListenerConnection()
        async with listener:
            task_status.started(listener.port)
            while True:
                client = await listener.accept()
                nursery.start_soon(_receiver, client)

    port = await nursery.start(_listener)
    events = []
    for i in range(3):
        event = Event()
        nursery.start_soon(_sender, port, event)
        events.append(event)

    for event in events:
        await event.wait()
