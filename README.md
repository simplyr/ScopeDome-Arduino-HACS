# ScopeDome Arduino Card 1.3 for Home Assistant

A Home Assistant integration for a ScopeDome dome with an Ethernet **Master** card and a paired **Slave** shutter card. It reports connection status, safety flags, inputs, the rotation counter, and motion, and provides shutter controls. It uses the local HTTP protocol described in the [official SDK](https://www.scopedome.com/wp-content/uploads/2020/10/ScopeDome_Arduino_Info_5.2SDK.pdf).

## Install with HACS

HACS must already be installed. If needed, follow the [official HACS installation guide](https://www.hacs.dev/docs/use/download/download/).

1. In Home Assistant, open **HACS → ⋮ → Custom repositories**. Enter `https://github.com/simplyr/ScopeDome-Arduino-HACS`, select **Integration**, and choose **Add**. See the [HACS custom repository instructions](https://www.hacs.dev/docs/faq/custom_repositories/).
2. Find **ScopeDome Arduino Card** in HACS and choose **Download**. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → ScopeDome Arduino Card**. Enter the local IPv4 address of the **Master** card, its HTTP port (usually `80`), and its HTTP password. The username is fixed to `scopedome` according to the [manufacturer's manual](https://www.scopedome.com/wp-content/uploads/2020/10/ScopeDome_Arduino_Card_Manual_EN.pdf). No `configuration.yaml` entry is needed.
4. Check the read-only values first: **Shutter card connected**, the safety flags, and **Shutter open input 1** / **Shutter close input 1**. Opening and closing remain disabled until the end-stop input polarity is confirmed.
5. Use the official ScopeDome Test App to check both inputs in two known physical shutter positions. Then select the verified active value, `0` or `1`, under **Configure → Shutter contact polarity**. Perform the first movement from Home Assistant while present and supervising the dome.

HACS provides updates for this integration. Restart Home Assistant after updating its Python files.

## Manual installation

Copy the entire `custom_components/scopedome_arduino` directory, including `translations`, to `<Home Assistant config>/custom_components/scopedome_arduino` and restart Home Assistant. Then follow steps 3–5 above. Use one installation method per Home Assistant instance so the source of future updates stays clear.

## Scope and safety

Setup sends only `getMode`, `getMac`, and `getStatus`; periodic polling sends `getStatus`. Movement commands are limited to `moveShutter=OPEN`, `moveShutter=CLOSE`, `stopShutter`, and `stopDome`. Opening and closing require a verified input polarity, a fresh valid status, a connected Slave card, no safety alarm, and no conflicting movement. Keep the manufacturer's safety rules, physical end stops, rain sensor, and UPS configured independently of Home Assistant.

The integration accepts the 12-group Master/Slave status format documented in SDK 5.2. The [Card 1.3 manual](https://www.scopedome.com/wp-content/uploads/2020/10/ScopeDome_Arduino_Card_Manual_EN.pdf) also mentions firmware 6.7 but does not provide a complete example of its HTTP status response. If your response format differs, setup fails safely. Adapting the parser would then require the firmware version and a redacted sample `getStatus` response.

The displayed rotation counter is in pulses, not degrees. Rotation to a target azimuth, seeking Home, and automatic weather-based opening are not implemented. HTTP Basic Auth does not use TLS here; connect only over a trusted local network or a protected VPN.

## Package checks

Run `python3 -m unittest discover -s tests -v` from the repository root. The mock tests make no network requests. This integration has not yet been tested against the physical controller or in a running Home Assistant instance.
