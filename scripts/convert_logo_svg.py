#!/usr/bin/env python3
"""Convert SVG logo to transparent PNG for banner use."""
from cairosvg import svg2png

with open("input/logo.svg", "rb") as f:
    svg_data = f.read()

svg_str = svg_data.decode("utf-8")
# Set color to white for dark banner backgrounds (已使用 currentColor 自动适配)
svg2png(
    bytestring=svg_str.encode("utf-8"),
    write_to="input/logo_svg.png",
    output_width=760,
    output_height=90,
    background_color="transparent",
)
print("Done: input/logo_svg.png")
