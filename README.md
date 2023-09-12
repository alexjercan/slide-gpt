# SlideGPT

CLI tool that can be used to generate a video using ChatGPT, DALLE-2 and
FakeYou.

### Dependencies

- [ffmpeg](https://ffmpeg.org/)

### Quickstart

To run the cli application locally you will need `ffmpeg` installed. Also make
sure to export your api key.

```console
sudo apt install ffmpeg
curl -sSL https://install.python-poetry.org | python3 -
export OPENAI_API_KEY=sk-...
export FAKEYOU_USERNAME=...
export FAKEYOU_PASSWORD=...
poetry install
echo "Please create a presentation about sunflowers." | poetry run slide-gpt
mpv videos/0/video.mp4
```

You can also change the speaker of the video using the `--speaker` flag with a
string taken from the [FakeYou](https://fakeyou.com/) website.
