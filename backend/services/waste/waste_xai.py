"""Grad-CAM attribution for the waste classifier.

WHAT THIS IS
------------
A real gradient-based explanation. It runs the SAME MobileNetV3 instance that produced the
prediction, hooks the last convolutional block, backpropagates the predicted logit, and weights
each of the 576 channels by the mean gradient flowing into it (Selvaraju et al., 2017). The
result is the model's own evidence for its own answer.

WHAT THIS IS NOT
----------------
It is not a picture generated to look explanatory. Nothing here asks a language model where to
put the heat, and nothing draws a decorative gradient over the crop. If gradients cannot be
computed — torch missing, no weights, a hook that never fired — `explain` raises `XaiUnavailable`
and `safe_explain` returns `{"available": False, "message": ...}` with **no image at all**. An
honest absence is worth more than a confident-looking image with no relationship to the model,
which is precisely the failure mode this module exists to avoid.

The heatmap explains the CLASSIFIER's decision about one crop. It says nothing about the
detector's box, and nothing about the segregation category, which is a configured policy mapping
rather than a model output.
"""

import base64
import io
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("ecosentinel.waste.xai")

#: Resolution of the attribution map before it is upsampled, i.e. the conv feature grid. Recorded
#: in the response so nobody reads a 7x7 map upsampled to 224x224 as pixel-level precision.
METHOD = "grad-cam"


class XaiUnavailable(Exception):
    """Attribution could not be computed. The caller reports this, never a substitute image."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _target_layer(model):
    """The last convolutional block of MobileNetV3.

    Grad-CAM needs the deepest layer that still has spatial extent: deep enough to carry class
    evidence, shallow enough that 'where' still means something. For this architecture that is
    `features[-1]`, a 576-channel 7x7 map at 224x224 input.
    """
    features = getattr(model, "features", None)
    if features is None or len(features) == 0:
        raise XaiUnavailable("The loaded classifier has no convolutional feature stack to attribute over.")
    return features[-1]


def explain(classifier: Any, image, target_index: Optional[int] = None) -> Dict[str, Any]:
    """One crop -> a Grad-CAM heatmap over the classifier's predicted class.

    Returns a dict with the overlay as a data URI, the class it explains, and the grid the
    attribution was computed at. Raises `XaiUnavailable` for every failure; it never substitutes
    a generated or decorative image.
    """
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise XaiUnavailable("torch and numpy are required for Grad-CAM attribution.") from exc

    try:
        model, classes, transform = classifier.loaded_model()
    except Exception as exc:  # noqa: BLE001 - includes ClassifierUnavailable
        raise XaiUnavailable(f"The classifier is not available for attribution ({exc}).") from exc

    layer = _target_layer(model)
    crop = image.convert("RGB")
    tensor = transform(crop).unsqueeze(0)

    activations: Dict[str, Any] = {}
    gradients: Dict[str, Any] = {}

    def forward_hook(_module, _inputs, output):
        activations["value"] = output

    def backward_hook(_module, _grad_in, grad_out):
        gradients["value"] = grad_out[0]

    # Read before the try block: the `finally` restores it, and a failure on this very line would
    # otherwise leave the name unbound and replace the real error with a NameError.
    was_training = model.training

    handles = [
        layer.register_forward_hook(forward_hook),
        # full_backward_hook is the non-deprecated form; older torch keeps the legacy name.
        (
            layer.register_full_backward_hook(backward_hook)
            if hasattr(layer, "register_full_backward_hook")
            else layer.register_backward_hook(backward_hook)
        ),
    ]

    try:
        # Gradients are required here, so this cannot reuse the inference path's no_grad context.
        model.eval()
        logits = model(tensor)
        # Detached copy for reporting: `logits` itself must stay in the graph for the backward
        # pass below, and reading a grad-tracking tensor as a float warns.
        probabilities = torch.softmax(logits, dim=1)[0].detach()
        index = int(probabilities.argmax()) if target_index is None else int(target_index)

        model.zero_grad(set_to_none=True)
        # Backpropagate the LOGIT, not the softmax probability: the softmax denominator couples
        # every class, so its gradient answers "why this class rather than the others" instead of
        # "what supports this class".
        logits[0, index].backward()

        if "value" not in activations or "value" not in gradients:
            raise XaiUnavailable("The attribution hooks did not fire on the target layer.")

        feature_maps = activations["value"].detach()[0]        # (C, H, W)
        channel_grads = gradients["value"].detach()[0]         # (C, H, W)

        # Grad-CAM proper: each channel weighted by the mean gradient flowing into it, summed,
        # then ReLU — negative contributions are evidence AGAINST the class and are not drawn.
        weights = channel_grads.mean(dim=(1, 2))
        cam = torch.relu((weights[:, None, None] * feature_maps).sum(dim=0))
        grid_h, grid_w = int(cam.shape[0]), int(cam.shape[1])

        peak = float(cam.max())
        if peak <= 0:
            # Every channel gradient was non-positive: the layer carries no positive evidence for
            # this class. Reporting a flat map as a heatmap would invent structure that is not there.
            raise XaiUnavailable(
                "No positive gradient reached the target layer, so there is nothing to attribute."
            )
        cam = (cam / peak).cpu().numpy()
    finally:
        for handle in handles:
            handle.remove()
        if was_training:
            model.train()

    overlay = _render(cam, crop, np)
    return {
        "method": METHOD,
        "available": True,
        "target_class": classes[index] if index < len(classes) else str(index),
        "target_confidence": round(float(probabilities[index]), 4),
        "layer": "features[-1]",
        # So a 7x7 map upsampled for display is never mistaken for pixel-level attribution.
        "attribution_grid": f"{grid_h}x{grid_w}",
        "overlay_image": overlay,
    }


def _render(cam, crop, np) -> str:
    """Heatmap over the crop, as a PNG data URI.

    The colour ramp is blue -> red through the map's own normalised values. It is a rendering of
    `cam` and nothing else: no smoothing that invents detail, no threshold that hides weak
    evidence.
    """
    from PIL import Image

    width, height = crop.size
    heat = Image.fromarray((cam * 255).astype("uint8")).convert("L").resize(
        (width, height), Image.BILINEAR
    )
    intensity = np.asarray(heat).astype("float32") / 255.0

    # Simple perceptual ramp: cold where the model found nothing, hot where it found its evidence.
    red = np.clip(intensity * 2.0, 0, 1)
    green = np.clip(1.0 - np.abs(intensity - 0.5) * 2.0, 0, 1)
    blue = np.clip((1.0 - intensity) * 2.0 - 1.0, 0, 1)
    colour = np.stack([red, green, blue], axis=-1)

    base = np.asarray(crop).astype("float32") / 255.0
    # Blend proportionally to intensity, so cold regions keep showing the original pixels and the
    # viewer can see WHAT the model was looking at, not only where.
    alpha = (intensity * 0.65)[..., None]
    blended = np.clip(base * (1 - alpha) + colour * alpha, 0, 1)

    buffer = io.BytesIO()
    Image.fromarray((blended * 255).astype("uint8")).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def safe_explain(classifier: Any, image, target_index: Optional[int] = None) -> Dict[str, Any]:
    """`explain` with every failure turned into a structured unavailability.

    Attribution is a diagnostic. It must never be able to fail an analysis that otherwise worked,
    and it must never quietly return something other than a real attribution.
    """
    try:
        return explain(classifier, image, target_index)
    except XaiUnavailable as exc:
        return {"method": METHOD, "available": False, "message": exc.message}
    except Exception as exc:  # noqa: BLE001
        logger.warning("waste_xai_failed", exc_info=True)
        return {
            "method": METHOD,
            "available": False,
            "message": f"Attribution failed unexpectedly ({exc.__class__.__name__}).",
        }
