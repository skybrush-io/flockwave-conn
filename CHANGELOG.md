# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [8.2.0]

### Added

- Added `BroadcastConnection` interface to mark connections that support
  broadcasting.

- Added `BroadcastAddressOverride` interface to mark connections that support
  overriding their broadcast addresses.

- Added `BroadcastMessageChannel` as a counterpart to `MesssageChannel` for
  connections that support broadcasting.

- Added `get_connection_capabilities()` to query the capabilities of a
  connection. This replaces the earlier undocumented `can_send` class
  property.

## [7.2.1]

### Fixed

- BroadcastUDPListenerConnection now binds to the broadcast address.

## [7.2.0]

### Added

- Added support for binding a UDP connection to a specific interface.

## [7.1.0]

### Added

- Added logging middleware for connections.

## [7.0.0]

### Changed

- Updated Trio to 0.24, which introduces breaking changes in the exception
  handling, hence it deserves a major version bump.

## [6.2.0]

### Removed

- Removed non-public `_broadcast_ttl` from UDPListenerConnection.

## [6.1.0]

### Added

- Added `create_loopback_connection_pair()` to create local loopback connections
  for testing purposes.

## [6.0.0]

### Changed

- `flockwave-net` dependency bumped to 4.0.

## [5.3.0]

### Changed

- `DummyConnection` is now readable and writable.

## [5.2.0]

### Added

- Added `FDConnection` as a base class.

## [5.1.0] - 2022-09-20

### Added

- Added `ProcessConnection` class to provide a bidirectional connection to a
  subprocess.

## [5.0.0] - 2022-04-27

### Removed

- Removed support for MIDI connections; it is now moved to the Skybrush Server
  extension that provides support for decoding SMPTE timecode.

## [4.0.1] - 2022-01-25

This is the release that serves as a basis for changelog entries above. Refer
to the commit logs for changes affecting this version and earlier versions.
