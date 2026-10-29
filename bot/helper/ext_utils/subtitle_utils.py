#!/usr/bin/env python3
"""
Intro Subtitle: adds a short softsub (a real, selectable subtitle track -
not burned into the video) that shows the user's own custom text for the
first few seconds of a leeched video, e.g. a channel/credit line. It's set
as the default subtitle track, so most players (VLC, MX Player, etc.) turn
it on automatically the moment the file is opened - even though Telegram's
own player doesn't show subtitle tracks at all.

Two output formats, depending on what the target container can actually
hold:
- MKV -> a real ASS (Advanced SubStation Alpha) track: supports color,
  background box and font size natively, and MKV carries it as-is.
- MP4 -> plain text (mov_text). MP4's subtitle format is fundamentally very
  limited and cannot carry an ASS track or reliable color/box/size styling
  no matter how it's muxed - so on MP4 only the text, duration and
  bottom-center position survive; color/background/font size only take
  effect on an MKV file.
"""

# ASS colors are &HAABBGGRR (alpha, then blue-green-red, reversed from the
# usual RGB order). AA=00 is fully opaque.
_ASS_COLOR_HEX = {
    "white":  "&H00FFFFFF",
    "black":  "&H00000000",
    "red":    "&H000000FF",
    "blue":   "&H00FF0000",
    "yellow": "&H0000FFFF",
    "green":  "&H0000FF00",
}


def validate_and_escape_subtitle_text(text):
    """
    Validate the user's raw subtitle text and strip anything that would
    break the generated subtitle file's single-block structure.

    Returns: (success: bool, result: str, error: str)
    """
    if not text or not text.strip():
        return False, "", "Subtitle text cannot be empty"

    text = text.strip()
    if len(text) > 200:
        return False, "", "Subtitle text too long (max 200 characters)"

    # Blank/newlines would break the single dialogue line/SRT block below.
    text = text.replace("\r", "").replace("\n", " ")
    # ASS treats these as control characters in a dialogue line.
    text = text.replace("{", "(").replace("}", ")")

    return True, text, ""


def _ass_escape(text):
    # Backslash starts an ASS override/line-break code - escape it so user
    # text is always shown literally.
    return text.replace("\\", "\\\\")


def create_ass_subtitle(intro_settings, video_path):
    """
    Build a styled .ass file (color, background box, font size all apply)
    for the intro text - used when the target container is MKV.
    """
    text = intro_settings.get("text", "")
    if not text:
        return None

    duration = intro_settings.get("duration", 5)
    color = intro_settings.get("color", "white")
    bg_color = intro_settings.get("bg_color", "none")
    font_size = intro_settings.get("font_size", 24)

    primary = _ASS_COLOR_HEX.get(color, _ASS_COLOR_HEX["white"])
    if bg_color == "none":
        # Outline + shadow only, no filled box behind the text.
        border_style = 1
        back_colour = "&H00000000"
    else:
        # Opaque box behind the text, in the chosen background color.
        border_style = 3
        back_colour = _ASS_COLOR_HEX.get(bg_color, "&H00000000")

    end_h, end_m, end_s = 0, duration // 60, duration % 60
    ass_content = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 384\n"
        "PlayResY: 288\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{font_size},{primary},&H000000FF,&H00000000,{back_colour},"
        f"0,0,0,0,100,100,0,0,{border_style},2,1,2,10,10,20,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,{end_h}:{end_m:02d}:{end_s:02d}.00,Default,,0,0,0,,{_ass_escape(text)}\n"
    )

    ass_path = video_path.rsplit(".", 1)[0] + ".intro.ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
    return ass_path


def create_srt_subtitle(intro_settings, video_path):
    """
    Build a plain .srt file (text + duration only, no styling) for the
    intro text - used when the target container is MP4, since MP4's
    subtitle format can't reliably carry color/box/font-size styling.
    """
    text = intro_settings.get("text", "")
    if not text:
        return None

    duration = intro_settings.get("duration", 5)
    srt_content = (
        "1\n"
        f"00:00:00,000 --> 00:00:{duration:02d},000\n"
        f"{text}\n"
    )

    srt_path = video_path.rsplit(".", 1)[0] + ".intro.srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    return srt_path


def create_subtitle_file(intro_settings, video_path, container_ext):
    """
    Create the intro subtitle file in whichever format the target
    container (container_ext, e.g. '.mkv' or '.mp4') can actually use.
    Returns (path, format) where format is 'ass' or 'srt', or
    (None, None) if there's no text configured.
    """
    if container_ext == ".mkv":
        path = create_ass_subtitle(intro_settings, video_path)
        return (path, "ass") if path else (None, None)
    path = create_srt_subtitle(intro_settings, video_path)
    return (path, "srt") if path else (None, None)


# Color options for the UI
COLOR_OPTIONS = {
    "white": "⚪ White",
    "black": "⚫ Black",
    "red": "🔴 Red",
    "blue": "🔵 Blue",
    "yellow": "🟡 Yellow",
    "green": "🟢 Green",
}

# Background color options (includes "none"). Only takes visible effect on
# MKV output - see create_subtitle_file's docstring.
BG_COLOR_OPTIONS = {
    "none": "❌ No Background",
    "white": "⚪ White",
    "black": "⚫ Black",
    "red": "🔴 Red",
    "blue": "🔵 Blue",
    "yellow": "🟡 Yellow",
    "green": "🟢 Green",
}
