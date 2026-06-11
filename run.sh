#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# Run AmbiHue with container environment (SUPERVISOR_TOKEN, etc.)
exec python3 /ambihue.py "$@"
