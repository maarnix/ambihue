# AmbiHue - Home Assistant Add-on Documentation

AmbiHue restores the connection between Philips Ambilight TVs and Hue Bridge by reading Ambilight data from the TV and forwarding it to Hue via the Entertainment Area API.

The Hue Entertainment Area provides low-latency color updates, offering significantly faster response times compared to standard light control via the Hue API.

**It is possible to get 15 updates per second!**

## Installation

1. Click the button below to add this repository to your Home Assistant instance:

   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmaarnix%2Fambihue)

2. Navigate to Settings → Add-ons → Add-on Store
3. Find "AmbiHue" in the list and click it
4. Click "INSTALL"

## Quick Start (Auto-Setup)

AmbiHue can automatically discover and configure your devices:

1. **Create an Entertainment Area** in the Philips Hue app first ([see tutorial](https://www.youtube.com/watch?v=OlXapdkedus))
2. **Press the button on your Hue Bridge**
3. **Start the add-on** - it will auto-discover your TV and Bridge
4. **Check the logs** for discovered lights and configure positions

### Auto-Discovery Flow

| Device | Discovery Method |
|--------|-----------------|
| **Hue Bridge** | Philips cloud portal + direct HTTPS API (works in Docker). Press Bridge button before or during startup. Polls for 30 seconds. |
| **Philips TV** | Home Assistant device registry (if `philips_js` integration exists), then SSDP network scan as fallback. |
| **Non-Android TV** | Connects without authentication after discovery. |
| **Android TV** | Two-phase PIN pairing (see below). |

### Android TV Pairing

Android TVs require PIN authentication, handled in two phases:

1. **Start the add-on** — a PIN code appears on your TV screen. The add-on saves a pairing key internally and exits.
2. Go to **Settings → Add-ons → AmbiHue → Configuration** and enter the PIN in the `pairing_pin` field. Save.
3. **Restart the add-on** — it pairs using the saved key and your PIN. Credentials are stored automatically.

> The `pairing_pin` field is only used during initial setup. After successful pairing, it can be left empty.
>
> For standalone usage, the PIN can also be entered directly in the terminal when prompted.

## Configuration

After auto-setup, you only need to configure the light positions. For manual setup, configure all three sections.

### 1. Ambilight TV Configuration

```yaml
ambilight_tv:
  protocol: "https://"
  ip: "192.168.1.100"    # Auto-discovered or set manually
  port: 1926
  api_version: 6
  user: ""               # Filled automatically for Android TVs
  password: ""           # Filled automatically for Android TVs
  pairing_pin: ""        # Temporary: for Android TV PIN entry
  refresh_rate_ms: 0     # Color update rate (0 = fastest possible)
  idle_refresh_rate_ms: 5000
  transition_smoothing: 0.5  # Color smoothing: 0.0 = instant, 0.95 = very smooth
```

### 2. Hue Entertainment Group Configuration

```yaml
hue_entertainment_group:
  ip: "192.168.1.50"           # Auto-discovered
  identification: "..."         # Auto-filled after pairing
  rid: "..."
  username: "..."
  app_id: "..."
  client_key: "..."
  swversion: 1972004020
  index: 0                      # Entertainment Area index
```

### 3. Lights Setup Configuration

Configure each light with its position relative to the TV:

```yaml
lights_setup:
  - name: "wall_left_down"
    id: 0                  # Light index from Entertainment Area
    positions: "0,1,3"     # Ambilight zones (comma-separated)
  - name: "wall_left_up"
    id: 1
    positions: "2,4,5"
  - name: "wall_right_up"
    id: 2
    positions: "8,9,11"
  - name: "wall_right_down"
    id: 3
    positions: "10,12,13"
```

**Finding Light IDs:** Check the add-on logs after Hue pairing:

```
============================================================
ENTERTAINMENT ZONES DISCOVERED
============================================================
Zone 0: Living Room
  Lights:
    [0] Hue Play Bar 1
    [1] Hue Play Bar 2
============================================================
```

**Ambilight Zone Map** (positions 0-16):

```text
[4] 0Top  [5]1T  [6]2T  [7]3T  [8]4T  [9]5T  [10]6T  [11]7T  [12] 8Top
[3] 3Left  ↗    →          →        →       →       →      ↘ [13] 0Right
[2] 2Left  ↑                                               ↓ [14] 1Right
[1] 1Left  ↑                                               ↓ [15] 2Right
[0] 0Left  ↑                                               ↓ [16] 3Right
```

## Verification

You can verify each component separately using command-line flags:

- Verify TV connection: `--verify tv --loglevel DEBUG`
- Verify Hue connection: `--verify hue --loglevel DEBUG`
- Discover Hue configuration: `--discover_hue --loglevel DEBUG`

When verifying the Hue connection, the first light (id=0) in your Entertainment Area should turn red.

## Testing

1. Use [this color test video](https://youtu.be/8u4UzzJZAUg?t=66) to verify that your lights are responding correctly
2. Watch the add-on logs to see real-time color updates and any errors
3. Adjust the `lights_setup` positions if colors don't match your expectations

## Automation with Home Assistant TV State

AmbiHue can automatically start when your TV turns on and stop when it turns off using Home Assistant automations.

### Configuration Modes

The add-on supports two operating modes controlled by timeout settings:

**Polling Mode (Default - wait_for_startup_s=29, runtime_error_threshold=10):**
- Add-on exits if TV not found within timeout
- Works without HA automations
- Best for simple setups

**Automation Mode (wait_for_startup_s=0, runtime_error_threshold=0):**
- Add-on waits indefinitely for TV and never exits
- Requires HA automations to start/stop based on TV state
- More efficient as HA controls lifecycle
- Best for advanced users with precise TV state control

### Setting Up Automation Mode

**Step 1: Configure the add-on for automation mode**

In the add-on configuration, set both timeout values to 0:

```yaml
ambilight_tv:
  protocol: "https://"
  ip: "192.168.1.100"
  port: "1926"
  api_version: "6"
  path: "ambilight/processed"
  wait_for_startup_s: 0         # Wait indefinitely
  runtime_error_threshold: 0    # Never exit on errors
  power_on_time_s: 8
```

**Step 2: Create Home Assistant Automations**

Your TV must be integrated in Home Assistant with a power state entity (e.g., `media_player.philips_tv`). Check that your TV shows as "on" or "off" in Home Assistant.

**Start AmbiHue when TV turns on:**

```yaml
automation:
  - alias: "Start AmbiHue when TV turns on"
    trigger:
      - platform: state
        entity_id: media_player.philips_tv
        to: "on"
    action:
      - service: hassio.addon_start
        data:
          addon: ambihue
```

**Stop AmbiHue when TV turns off:**

```yaml
automation:
  - alias: "Stop AmbiHue when TV turns off"
    trigger:
      - platform: state
        entity_id: media_player.philips_tv
        to: "off"
    action:
      - service: hassio.addon_stop
        data:
          addon: ambihue
```

**Via UI:**
1. Go to Settings → Automations & Scenes → Create Automation
2. Trigger: State of your TV entity changes to "on"
3. Action: Call service `hassio.addon_start` with addon `ambihue`
4. Repeat for "off" state with `hassio.addon_stop`

### Resilient Operation

When using automation mode (or any configuration):
- If the TV turns off during operation, AmbiHue pauses light updates
- When the TV turns back on, syncing resumes automatically
- The add-on logs state transitions for monitoring
- In automation mode, the add-on continues running even if TV is offline

## Troubleshooting

### Auto-Setup Issues
- **"Hue Bridge pairing timed out"**: Press the Bridge button and restart the add-on
- **"TV PAIRING REQUIRED"**: This is expected for Android TVs. Enter the PIN shown on TV in the config
- **"No Philips TVs found"**: Set the TV IP manually in the configuration
- **PIN not working**: Make sure to enter the exact PIN shown on TV. If the add-on was restarted without entering a PIN, the pairing key expires and a new PIN will be generated on the next start.

### TV Connection Issues
- Verify the TV IP address is correct
- Check if your TV API version is correct (usually 6 for newer models, 5 for older)
- For Android TVs, the add-on handles pairing automatically via the `pairing_pin` field
- For manual setup, try using [pylips](https://github.com/eslavnov/pylips) to get credentials

### Hue Connection Issues
- Ensure your Entertainment Area is created in the Hue app **before** starting AmbiHue
- Press the Bridge button **before** starting the add-on (or within 30 seconds)
- Make sure the `index` value matches your Entertainment Area
- Check that lights are added to the Entertainment Area

### Performance Issues
- Update rate depends on TV API response time (~5-15 Hz typical)
- Set `refresh_rate_ms: 0` for maximum throughput (default)
- Adjust `transition_smoothing` (0.0–0.95) to balance responsiveness vs. smoothness
- Reduce the number of lights or positions if experiencing lag
- Check network latency between Home Assistant, TV, and Hue Bridge

### Lights Not Matching Screen Colors
- Adjust the `A_positions`, `B_positions`, etc. arrays to match physical placement
- Use the position index map above as reference
- Test with the color test video to verify mapping

## Support

For issues, feature requests, or contributions, visit:
https://github.com/maarnix/ambihue/issues

## Advanced Options

These options can be set in `userconfig.yaml` (standalone) or are available as internal defaults:

| Option | Default | Description |
|--------|---------|-------------|
| `refresh_rate_ms` | `0` | Delay between color updates (0 = fastest possible) |
| `idle_refresh_rate_ms` | `5000` | Poll rate when TV screen is black or session inactive |
| `transition_smoothing` | `0.5` | Exponential smoothing factor (0.0 = instant, 0.95 = very smooth) |
| `black_screen_timeout_s` | `30` | Seconds of black screen before tearing down Hue session |
| `wait_for_startup_s` | `29` | Seconds to wait for TV at startup (0 = wait indefinitely) |
| `runtime_error_threshold` | `10` | Exit after N consecutive TV errors (0 = never exit) |
| `power_on_time_s` | `8` | Grace period for TV to finish booting |

## Technical Details

- **Update Rate:** Limited by TV API response time (~5-15 Hz typical) via Hue Entertainment Area API
- **Supported Architectures:** aarch64, amd64, armv7
- **Network Requirements:** Access to both TV (port 1926/8080) and Hue Bridge
- **Dependencies:** Python 3.12, httpx, hue-entertainment-pykit

## License

See the project repository for license information.
