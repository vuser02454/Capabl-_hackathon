

def test_decoded_frames_are_bgr_for_ultralytics():
    """Ultralytics treats a bare ndarray as BGR, because a file path is loaded with OpenCV.

    Handing it RGB does not raise — it silently detects less, which is how this went unnoticed in
    production. Measured on the 59 held-out TACO test images at the production threshold, the same
    pixels as RGB rather than BGR cost the waste detector 62 detections against 114.
    """
    import io

    import numpy as np
    from PIL import Image

    from services.water_vision_service import _decode_image

    buffer = io.BytesIO()
    # Pure red in RGB terms. Decoded for ultralytics it must arrive with red in the LAST channel.
    Image.new("RGB", (8, 8), (255, 0, 0)).save(buffer, format="PNG")

    decoded = _decode_image(buffer.getvalue())

    assert decoded.shape == (8, 8, 3)
    assert tuple(decoded[0, 0]) == (0, 0, 255)
    # torch cannot share a negative-stride view, so the array must be contiguous.
    assert decoded.flags["C_CONTIGUOUS"]


def test_decoded_frame_dimensions_survive_the_channel_swap():
    """Width and height are read off this array, so the swap must not disturb them."""
    import io

    from PIL import Image

    from services.water_vision_service import _decode_image

    buffer = io.BytesIO()
    Image.new("RGB", (30, 12), (10, 20, 30)).save(buffer, format="PNG")

    decoded = _decode_image(buffer.getvalue())

    assert decoded.shape[0] == 12 and decoded.shape[1] == 30
