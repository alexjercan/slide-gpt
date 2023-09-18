"""Create a video from a slide presentation"""

import argparse
import glob
import json
import logging
import os
import re
import sys
import urllib.request
import wave
from dataclasses import dataclass
from typing import Dict, Tuple

import fakeyou
import ffmpeg
import openai
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)

FK = fakeyou.FakeYou()

try:
    FK.login(
        username=os.environ["FAKEYOU_USERNAME"],
        password=os.environ["FAKEYOU_PASSWORD"],
    )
except KeyError:
    logging.warning("No login credentials found for FakeYou")
except fakeyou.exception.InvalidCredentials:
    logging.warning("Invalid login credentials for FakeYou")
except fakeyou.exception.TooManyRequests:
    logging.warning("Too many requests for FakeYou")

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
VOICES = FK.list_voices()


@dataclass
class Args:
    """Arguments for the pipeline"""

    model: str
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
        "--model",
        help="The openai model to use for generating the slides",
        default="gpt-3.5-turbo",
        choices=["gpt-3.5-turbo", "gpt-4"],
        required=False,
    )
    parser.add_argument(
        "--speaker",
        help="The speaker title to use for the presentation",
        default="Morgan Freeman (New)",
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

    return Args(args.model, prompt, speaker, args.output)


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
    model: str, system: str, prompt: str, speaker: str, output: str
):
    """Create the slides for the presentation

    The slides will be saved in the output directory as `slide_*.png` and
    `slide_*.wav`. The slides will be created by using the system prompt and
    the user prompt.

    Parameters
    ----------
    model : str
        The openai model to use for generating the slides
    system : str
        The system prompt to use for the presentation
    prompt : str
        The user prompt to use for the presentation
    speaker : str
        The speaker to use for the presentation
    output : str
        The output directory to use for the files
    """
    logging.info("Creating slides...")

    with open(
        os.path.join(output, "prompt.txt"), "w", encoding="utf-8"
    ) as file:
        file.write(prompt)

    response = openai.ChatCompletion.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": system,
            },
            {"role": "user", "content": prompt},
        ],
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
                prompt=slide["image"], n=1, size="1024x1024"
            )
            image_url = response["data"][0]["url"]

            path = os.path.join(output, f"slide_{index:02d}.png")
            urllib.request.urlretrieve(image_url, path)

            progress.set_description(
                f"Slide {index}: TTS ({speaker}) '{slide['text']}' ..."
            )

            path = os.path.join(output, f"slide_{index}.wav")
            FK.say(slide["text"], speaker).save(path)

            progress.update(1)


def srt_seconds_to_hh_mm_ss_mmm(seconds: float) -> str:
    """Convert seconds to HH:MM:SS,mmm format

    Parameters
    ----------
    seconds : float
        The seconds to convert

    Returns
    -------
    str
        The seconds in HH:MM:SS,mmm format
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    r_seconds = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)

    result = f"{hours:02d}:{minutes:02d}:{r_seconds:02d},{milliseconds:03d}"

    return result


def numerical_sort(filename: str) -> str | int:
    """Sort the filenames numerically

    Parameters
    ----------
    filename : str
        The filename to sort

    Returns
    -------
    str | int
        The filename as a number if it contains a number, otherwise the filename
    """
    match = re.search(r"\d+", filename)
    if match:
        return int(match.group())

    return filename


def create_srt(output: str):
    """Create the SRT file for the presentation

    The SRT file will be saved in the output directory as `video.srt`.
    The timing for each slide will be based on the `.wav` length.

    Parameters
    ----------
    output : str
        The output directory to use for the files
    """
    logging.info("Creating srt...")

    audio_files = sorted(
        glob.glob(os.path.join(output, "slide_*.wav")), key=numerical_sort
    )

    with open(
        os.path.join(output, "presentation.json"), "r", encoding="utf-8"
    ) as file:
        presentation = json.load(file)

    with open(
        os.path.join(output, "video.srt"), "w", encoding="utf-8"
    ) as file:
        current_s = 0

        for index, (slide, audio_file) in enumerate(
            zip(presentation, audio_files)
        ):
            with open(audio_file, "rb") as audio_f:
                audio = wave.open(audio_f)
                duration = audio.getnframes() / audio.getframerate()

            start = current_s
            end = current_s + duration

            start_fmt = srt_seconds_to_hh_mm_ss_mmm(start)
            end_fmt = srt_seconds_to_hh_mm_ss_mmm(end)

            file.write(f"{index + 1}\n")
            file.write(f"{start_fmt} --> {end_fmt}\n")
            file.write(f"{slide['text']}\n")
            file.write("\n")

            current_s = end


def vtt_seconds_to_hh_mm_ss_mmm(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format

    Parameters
    ----------
    seconds : float
        The seconds to convert

    Returns
    -------
    str
        The seconds in HH:MM:SS.mmm format
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    r_seconds = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)

    result = f"{hours:02d}:{minutes:02d}:{r_seconds:02d}.{milliseconds:03d}"

    return result


def create_vtt(output: str):
    """Create the VTT file for the presentation

    The SRT file will be saved in the output directory as `video.vtt`.
    The timing for each slide will be based on the `.wav` length.

    Parameters
    ----------
    output : str
        The output directory to use for the files
    """
    logging.info("Creating vtt...")

    audio_files = sorted(glob.glob(os.path.join(output, "slide_*.wav")))

    with open(
        os.path.join(output, "presentation.json"), "r", encoding="utf-8"
    ) as file:
        presentation = json.load(file)

    with open(
        os.path.join(output, "video.vtt"), "w", encoding="utf-8"
    ) as file:
        current_s = 0

        file.write("WEBVTT\n\n")

        for index, (slide, audio_file) in enumerate(
            zip(presentation, audio_files)
        ):
            with open(audio_file, "rb") as audio_f:
                audio = wave.open(audio_f)
                duration = audio.getnframes() / audio.getframerate()

            start = current_s
            end = current_s + duration

            start_fmt = vtt_seconds_to_hh_mm_ss_mmm(start)
            end_fmt = vtt_seconds_to_hh_mm_ss_mmm(end)

            file.write(f"{index + 1}\n")
            file.write(f"{start_fmt} --> {end_fmt}\n")
            file.write(f"{slide['text']}\n")
            file.write("\n")

            current_s = end


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
    ).overwrite_output().run()


def pipeline(args: Args) -> str:
    """Run the pipeline

    Parameters
    ----------
    args : Args
        The arguments for the pipeline

    Returns
    -------
    str
        The run number for this pipeline, used to identify the output folder
    """
    logging.info("Running pipeline with args: %s", args)

    model = args.model
    prompt = args.prompt
    speaker = args.speaker
    output, run = get_output_run(args.output)

    create_slides(model, SYSTEM, prompt, speaker, output)
    create_vtt(output)
    create_srt(output)
    create_video(output)

    return run


def main():
    """Main"""
    pipeline(parse_args())


if __name__ == "__main__":
    main()
