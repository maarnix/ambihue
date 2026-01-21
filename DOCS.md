# AmbiHue - Home Assistant Add-on Documentation

AmbiHue restores the connection between Philips Ambilight TVs and Hue Bridge by reading Ambilight data from the TV and forwarding it to Hue via the Entertainment Area API.

The Hue Entertainment Area provides low-latency color updates, offering significantly faster response times compared to standard light control via the Hue API.

**It is possible to get 15 updates per second!**

## Installation

1. Click the button below to add this repository to your Home Assistant instance:

   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fklimak000%2Fambihue)

2. Navigate to Settings → Add-ons → Add-on Store
3. Find "AmbiHue" in the list and click it
4. Click "INSTALL"

## Configuration

Before starting the add-on, you need to configure three sections:

### 1. Ambilight TV Configuration

Configure your Philips Ambilight TV connection:

```yaml
ambilight_tv:
  protocol: "https://"
  ip: "192.168.1.100"  # Replace with your TV's IP address
  port: "1926"
  api_version: "6"
  path: "ambilight/processed"
  wait_for_startup_s: 29
  power_on_time_s: 8
```

**For Android TVs with authentication:**
If your TV requires authentication (common with newer Android TVs), you'll need to add credentials obtained using [pylips](https://github.com/eslavnov/pylips):

```yaml
ambilight_tv:
  protocol: "https://"
  ip: "192.168.1.100"
  port: "1926"
  api_version: "6"
  path: "ambilight/processed"
  wait_for_startup_s: 29
  power_on_time_s: 8
  user: "your_username_from_pylips"
  password: "your_password_from_pylips"
```

### 2. Hue Entertainment Group Configuration

Before configuring, you must:
1. Create an Entertainment Area in the Philips Hue app ([see official tutorial](https://www.youtube.com/watch?v=OlXapdkedus))
2. Add the lights you want to sync to this Entertainment Area
3. Use the discovery feature (see below) to get your bridge credentials

**Discovery Command:**
To automatically discover your Hue Bridge configuration, you can use the built-in discovery feature. Install the add-on first, then run with the `--discover_hue` flag using the add-on logs or via SSH.

```yaml
hue_entertainment_group:
  _identification: "bridge_id_here"
  _rid: "entertainment_area_rid"
  _ip_address: "192.168.1.50"  # Your Hue Bridge IP
  _swversion: 1972004020
  _username: "generated_username"
  _hue_app_id: "generated_app_id"
  _client_key: "generated_client_key"
  _name: "Hue Bridge"
  index: 0  # Entertainment Area index (usually 0)
```

### 3. Lights Setup Configuration

Configure the physical position of your lights relative to your TV. Each light can use color data from multiple TV zones.

**Position Index Map:**

```text
[4] 0Top  [5]1T  [6]2T  [7]3T  [8]4T  [9]5T  [10]6T  [11]7T  [12] 8Top
[3] 3Left  ↗    →          →        →       →       →      ↘ [13] 0Right
[2] 2Left  ↑                                               ↓ [14] 1Right
[1] 1Left  ↑                                               ↓ [15] 2Right
[0] 0Left  ↑                                               ↓ [16] 3Right
```

**Example Configuration:**
For four lights positioned around your TV (left down, left up, right up, right down):

```yaml
lights_setup:
  A_name: "wall_left_down"
  A_id: 0  # Light ID within Entertainment Area (not global Hue ID)
  A_positions: [0, 1, 3]
  B_name: "wall_left_up"
  B_id: 1
  B_positions: [2, 4, 5]
  C_name: "wall_right_up"
  C_id: 2
  C_positions: [8, 9, 11]
  D_name: "wall_right_down"
  D_id: 3
  D_positions: [10, 12, 13]
```

**Important:** The `A_id`, `B_id`, `C_id`, `D_id` values refer to the light's position within your Entertainment Area, NOT the global Hue light ID.

## How to Configure

1. After installing the add-on, go to the add-on page
2. Click on the "Configuration" tab
3. Click the three dots (⋮) and select "Edit in YAML"
4. Paste your complete configuration following the structure above
5. Click "SAVE"
6. Go to the "Info" tab and click "START"

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

### TV Connection Issues
- Verify the TV IP address is correct
- Check if your TV API version is correct (usually 6 for newer models, 5 for older)
- For Android TVs, ensure you've added user/password credentials
- Try using [pylips](https://github.com/eslavnov/pylips) for TV discovery

### Hue Connection Issues
- Ensure your Entertainment Area is created in the Hue app
- Verify the Hue Bridge IP address
- Make sure the `index` value matches your Entertainment Area
- Check that lights are added to the Entertainment Area

### Performance Issues
- The add-on sends up to 15 updates per second
- Reduce the number of lights or positions if experiencing lag
- Check network latency between Home Assistant, TV, and Hue Bridge

### Lights Not Matching Screen Colors
- Adjust the `A_positions`, `B_positions`, etc. arrays to match physical placement
- Use the position index map above as reference
- Test with the color test video to verify mapping

## Support

For issues, feature requests, or contributions, visit:
https://github.com/klimak000/ambihue/issues

## Technical Details

- **Update Rate:** Up to 15 updates per second via Hue Entertainment Area API
- **Supported Architectures:** aarch64, amd64, armv7
- **Network Requirements:** Access to both TV (port 1926/8080) and Hue Bridge
- **Dependencies:** Python 3.12, httpx, hue-entertainment-pykit

## License

See the project repository for license information.
