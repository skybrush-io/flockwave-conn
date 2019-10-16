from flockwave.connections import UDPSocketConnection


async def test_udp_socket_connection():
    sender = UDPSocketConnection("127.0.0.1")
    receiver = UDPSocketConnection("127.0.0.1")

    async with sender, receiver:
        await sender.write((b"helo", receiver.address))
        data, address = await receiver.read()
        assert data == b"helo"
        assert address == sender.address
