from pytest import raises

from flockwave.networking import is_mac_address_unicast, is_mac_address_universal


def test_is_mac_address_universal():
    universal = is_mac_address_universal

    assert universal("4c:32:75:9b:66:03")
    assert not universal("82:17:01:36:9f:00")
    assert not universal("ff:ff:ff:ff:ff:ff")

    with raises(ValueError):
        universal("foobarbaz")

    with raises(ValueError):
        universal("gg:17:01:36:9f:00")


def test_is_mac_address_unicast():
    unicast = is_mac_address_unicast

    assert unicast("4c:32:75:9b:66:03")
    assert unicast("82:17:01:36:9f:00")
    assert not unicast("ff:ff:ff:ff:ff:ff")
    assert not unicast("11:22:33:44:55:66")

    with raises(ValueError):
        unicast("foobarbaz")

    with raises(ValueError):
        unicast("gg:17:01:36:9f:00")
