"""Create a video from a slide presentation"""

import argparse
import glob
import json
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import fakeyou
import ffmpeg
import openai
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)

SYSTEM = """Your job is to create a slide presentation for a video. \
In this presentation you must include a speech for the current slide and a \
description for the background image. You need to make it as story-like as \
possible. The format of the output must be in JSON. You have to output a list \
of objects. Each object will contain a key for the speech called "text" and a \
key for the image description called "image".

For example for a slide presentation about the new iphone you could output \
something like:

```
[
  {
    "text": "Hello. Today we will discuss about the new iphone",
    "image": "Image of a phone on a business desk with a black background"
  },
  {
    "text": "Apple is going to release this new iphone this summer",
    "image": "A group of happy people with phones in their hand"
  },
  {
    "text": "Thank you for watching my presentation",
    "image": "A thank you message on white background"
  }
]
```

Make sure to output only JSON text. Do not output any extra comments.
"""
SPEAKER = "TM:cpwrmn5kwh97"
VOICES = fakeyou.FakeYou().list_voices()


@dataclass
class Args:
    """Arguments for the pipeline"""

    prompt: str
    speaker: str
    output: str


def parse_args() -> Args:
    """Parse the arguments for the pipeline

    Returns
    -------
    Args
        The arguments for the pipeline
    """
    parser = argparse.ArgumentParser(
        description="Create a video from a slide presentation"
    )
    parser.add_argument(
        "--speaker",
        help="The speaker title to use for the presentation",
        default="Morgan Freeman",
        required=False,
    )
    parser.add_argument(
        "--output",
        help="The output directory to use for the files",
        default="videos",
        required=False,
    )

    args = parser.parse_args()

    assert args.speaker in VOICES.title, "Invalid speaker"

    speaker = get_voices().get(args.speaker, SPEAKER)
    prompt = sys.stdin.read()

    return Args(prompt, speaker, args.output)


def get_output_run(output: str) -> Tuple[str, str]:
    """Create a new folder inside the output directory for this run

    Parameters
    ----------
    output : str
        The output directory to use for the files

    Returns
    -------
    Tuple[str, str]
        The path to the run directory and the run number
    """
    if not os.path.exists(output):
        os.mkdir(output)

    run = 0
    while os.path.exists(os.path.join(output, str(run))):
        run += 1

    run_path = os.path.join(output, str(run))
    os.mkdir(run_path)

    return run_path, str(run)


def get_voices() -> Dict[str, str]:
    """Get the map of available voices

    Returns
    -------
    Dict[str, str]
        The map of available voices
    """
    return dict(zip(VOICES.title, VOICES.modelTokens))


def create_slides(
    system: str,
    prompt: str,
    speaker: str,
    output: str,
    api_key: Optional[str] = None,
):
    """Create the slides for the presentation

    The slides will be saved in the output directory as `slide_*.png` and
    `slide_*.wav`. The slides will be created by using the system prompt and
    the user prompt.

    Parameters
    ----------
    system : str
        The system prompt to use for the presentation
    prompt : str
        The user prompt to use for the presentation
    speaker : str
        The speaker to use for the presentation
    output : str
        The output directory to use for the files
    api_key : Optional[str], optional
        The OpenAI API key to use for the requests
    """
    logging.info("Creating slides...")

    with open(
        os.path.join(output, "prompt.txt"), "w", encoding="utf-8"
    ) as file:
        file.write(prompt)

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": system,
            },
            {"role": "user", "content": prompt},
        ],
        api_key=api_key,
    )

    presentation = json.loads(response.choices[0].message.content)

    with open(
        os.path.join(output, "presentation.json"), "w", encoding="utf-8"
    ) as file:
        json.dump(presentation, file, indent=2)

    with tqdm(total=len(presentation)) as progress:
        for index, slide in enumerate(presentation):
            progress.set_description(
                f"Slide {index}: Image '{slide['image']}' ..."
            )

            response = openai.Image.create(
                prompt=slide["image"],
                n=1,
                size="1024x1024",
                api_key=api_key,
            )
            image_url = response["data"][0]["url"]

            path = os.path.join(output, f"slide_{index}.png")
            urllib.request.urlretrieve(image_url, path)

            progress.set_description(
                f"Slide {index}: TTS ({speaker}) '{slide['text']}' ..."
            )

            path = os.path.join(output, f"slide_{index}.wav")
            fakeyou.FakeYou().say(slide["text"], speaker).save(path)

            progress.update(1)


def create_video(output: str):
    """Create the video from the slides

    The video will be saved in the output directory as `video.mp4`. The video
    will be created by concatenating the images and audio files together.

    Parameters
    ----------
    output : str
        The output directory to use for the files

    Raises
    ------
    ValueError
        If the number of image and audio files is not the same
    """
    logging.info("Creating video...")

    image_files = sorted(glob.glob(os.path.join(output, "slide_*.png")))
    audio_files = sorted(glob.glob(os.path.join(output, "slide_*.wav")))

    if len(image_files) != len(audio_files):
        raise ValueError("Number of image and audio files must be the same")

    input_streams = []
    for image_file, audio_file in zip(image_files, audio_files):
        input_streams.append(ffmpeg.input(image_file))
        input_streams.append(ffmpeg.input(audio_file))

    ffmpeg.concat(*input_streams, v=1, a=1).output(
        os.path.join(output, "video.mp4"),
        pix_fmt="yuv420p",
    ).run()


def pipeline(args: Args, api_key: Optional[str] = None) -> str:
    """Run the pipeline

    Parameters
    ----------
    args : Args
        The arguments for the pipeline
    api_key : Optional[str], optional
        The OpenAI API key to use, by default None

    Returns
    -------
    str
        The run number for this pipeline, used to identify the output folder
    """
    logging.info("Running pipeline with args: %s", args)

    prompt = args.prompt
    speaker = args.speaker
    output, run = get_output_run(args.output)

    create_slides(SYSTEM, prompt, speaker, output, api_key)
    create_video(output)

    return run


def main():
    """Main"""
    pipeline(parse_args())


if __name__ == "__main__":
    main()
