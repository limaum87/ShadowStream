# Raspberry Radio Output

This project exposes a web UI on port `10000`, but the audio playback happens on the Raspberry hardware through `mpv` inside the container.

## Run

```bash
docker compose up -d --build
```

Open `http://IP_DO_RASPBERRY:10000` from any device on your network.

## How it works

- The browser is only a remote control.
- The container runs `mpv` and sends audio to `/dev/snd` on the Raspberry.
- `Play`, `Pause`, `Stop`, and volume changes affect the Raspberry output, not the client browser.

## Notes

- `devices: /dev/snd:/dev/snd` is required for ALSA audio output.
- If your Raspberry uses a specific ALSA device, set `MPV_AUDIO_DEVICE` in `docker-compose.yml`.
- Edit `app/stations.json` to add or remove stations.
