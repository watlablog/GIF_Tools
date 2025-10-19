# GIF Utility Suite

Collection of PyQt5 desktop tools for working with GIF images. All utilities offer drag-and-drop driven workflows and provide immediate previews of the resulting animations.

## Tools Overview

### `create_gif.py` – Build a GIF from still images
- Drop a folder of images (or individual files) to build a single animated GIF.
- Configure frame rate (FPS) and resizing options, including an optional aspect-ratio lock.
- Generated GIFs can be reviewed on the Preview tab; scrollbars allow full-size inspection without auto-scaling.

### `trim_gif.py` – Crop an existing GIF
- Drag in a GIF, then drag the green rectangle to set the crop area.
- Inspect each frame with the slider before saving.
- Choose an output path and click **Trim GIF**; the result is shown on the Preview tab with scrollbars for large animations.

### `combine_gif.py` – Join two GIFs side by side
- Drop one GIF on the left and another on the right; the tool concatenates them horizontally.
- When frame counts differ, the shorter GIF reuses its last frame; when heights differ, white padding is added.
- Frame rate defaults to the faster GIF but can be overridden.
- Preview the merged result on the second tab; scrollbars ensure the full animation remains visible.

### `decomposition_gif.py` – Split a GIF into individual frames
- Drop a GIF to list all frames and preview them with the slider.
- Specify an output directory and click **Decomposition** to export numbered PNG files. Padding width is adjusted automatically (e.g., 001–010, 0001–0100).
- Optional resizing (with aspect-ratio lock) can be applied to each exported frame.
- The original animation is available on the Preview tab, again with scrollbars for large GIFs.

## Notes
- All tools require a GUI environment because they rely on PyQt5.
- Pillow handles GIF decoding/encoding; unsupported or invalid frames are safely skipped.
- Scrollbars are enabled on every preview tab so that oversized animations can be inspected without forced scaling.

