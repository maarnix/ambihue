# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2025-01-XX

### Added
- HTTPX library integration for faster HTTP/2 communication with TV
- Performance improvements: reduced API response time from 90ms to 55ms
- Enhanced logger with proper level getter functionality
- Debug time measurements for performance profiling

### Changed
- Replaced `requests` library with `httpx` for better performance
- Updated main loop sleep time to 10ms for better responsiveness
- Improved error handling and logging throughout the application

### Fixed
- Fixed lights_setup configuration issues
- Clarified setup steps in documentation

## [1.1.1] - 2025-01-XX

### Added
- ARM platform support (armv7, aarch64)
- Enhanced Home Assistant integration documentation

### Changed
- Optimized main loop sleep time from 10ms to 1ms for better performance
- Improved logger level getter implementation

### Fixed
- Various stability improvements for ARM architectures

## [1.1.0] - 2025-01-XX

### Added
- Home Assistant add-on integration
- Configuration loading from Home Assistant `/data/options.json`
- Multi-architecture Docker build support (amd64, aarch64, armv7)
- GitHub Actions workflows for CI/CD
- Super-Linter integration for code quality

### Changed
- Restructured configuration to support both standalone and HA modes
- Updated documentation with Home Assistant installation instructions

## [1.0.1] - 2025-01-XX

### Added
- DigestAuth support for Android TV authentication
- User/password authentication for newer Philips Android TVs

### Fixed
- Authentication issues with Android-based Philips TVs

## [1.0.0] - Initial Release

### Added
- Core functionality to sync Philips Ambilight with Hue lights
- Support for Hue Entertainment Area API (15 updates/second)
- Configurable light positioning with 17 TV zones
- Support for up to 4 lights (A, B, C, D)
- TV connection verification
- Hue Bridge connection verification
- Automatic Hue Entertainment Area discovery
- Color averaging from multiple TV zones
- RGB to CSS color name conversion
- Comprehensive logging with colored output
- Configuration via YAML files
- Multi-stage Docker build with linters
- Support for Philips TV API v1, v5, and v6
- Graceful error handling and TV connection monitoring
