# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [9.2.0]

### Added

- `supervise()` now takes an optional `name` argument that can be used to
  provide a human-readable name for the supervision task, to be used
  in instrumentation logs.

## [9.1.0]

### Changed

- `UDPListenerConnection` now attempts to maximize the size of its receive
  buffer to avoid dropping packets under high load. You can set its
  `maximize_receive_buffer` property to `False` to get back the old behaviour.

## [9.0.0]

### Breaking changes

- Dropped support for Python 3.9.

## [8.4.1]

### Fixed

- `ConnectionSupervisor` now closes supervised connections when they were not
  open at the time when they were added to the supervisor.

## [8.4.0]

### Added

- Added `register_builtin_middleware()` to register the built-in middleware on
  an existing connection factory.

### Changed

- The default `create_connection()` factory now registers the `log`, `rd` and
  `wr` middleware at import time.

## [8.3.0]

### Added

- Added `ReadOnlyMiddleware` and `WriteOnlyMiddleware` to make existing
  bidirectional connections read-only or write-only.

### Fixed

- `BroadcastAddressOverride` is now exported properly.

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
