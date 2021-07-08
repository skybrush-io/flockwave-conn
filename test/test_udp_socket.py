from flockwave.connections import UDPListenerConnection, UDPSocketConnection


async def test_udp_socket_connection():
    receiver = UDPListenerConnection("127.0.0.1")
    async with receiver:
        address = receiver.address
        assert address is not None

        sender = UDPSocketConnection(*address)
        async with sender:
            await sender.write(b"helo")
            data, address = await receiver.read()
            assert data == b"helo"
            assert address == sender.address
            assert address is not None

            await receiver.write((b"spam", address))
            data = await sender.read()
            assert data == b"spam"
