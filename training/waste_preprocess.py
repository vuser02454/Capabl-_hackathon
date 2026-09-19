"""The one definition of how a waste image becomes a tensor.

This file exists because training and serving disagreed, silently and expensively.

The classifier was trained and validated on `garbage_Dataset`, whose images are roughly square
full-frame photographs of one object. Validation preprocessing was `Resize(short side to 258)` then
`CenterCrop(224)`, which on a square photo keeps almost everything, and the model scored macro-F1
0.911.

At inference it is fed **detector crops**, which are not square. A bottle crop is typically 2.6x
taller than it is wide. `Resize(258)` makes that 258x680, and `CenterCrop(224)` then keeps a
224x224 patch from the middle — roughly a fifth of the object, usually just the label. The shape
that makes a bottle a bottle is thrown away before the network sees a pixel.

Measured on 145 real detector crops of plastic bottles, the only change being the transform:

    Resize + CenterCrop (what was served) : 36% classified plastic_bottles
    Resize to square, ignoring aspect     : 56%
    Letterbox (below)                     : 87%

So preprocessing is not a detail of the training script. Both sides import it from here, and the
checkpoint records which version produced it, so a future change cannot quietly reintroduce the
gap.
"""

from typing import Tuple

#: Versions the EVALUATION transform — the one serving applies — and nothing else. Stored in every
#: checkpoint and compared on load, so a model trained under different preprocessing is flagged
#: rather than silently mispredicting. Training augmentation is versioned separately below,
#: because changing it does not change what serving must do.
PREPROCESS_VERSION = "letterbox_v2"

#: Versions the training augmentation. Recorded in the manifest for reproducibility; serving never
#: compares against it, because augmentation is not applied at inference.
AUGMENTATION_VERSION = "boxjitter_v2"

#: ImageNet statistics, which the pretrained MobileNet backbone expects.
MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]

#: Neutral grey fill for the padding. Mid-grey lands near zero after normalisation, so the padding
#: contributes as little as possible rather than reading as a black or white object edge.
PAD_COLOR = (124, 116, 104)


def letterbox(image, size: int):
    """Fit a PIL image into `size` x `size` without distorting it, padding the short side.

    Aspect ratio is preserved because it is a feature: a bottle is tall, a can is squat, a bag is
    irregular. Squashing every crop to a square erases that distinction, and cropping to a square
    erases the object.
    """
    from PIL import Image

    width, height = image.size
    if width <= 0 or height <= 0:
        return Image.new("RGB", (size, size), PAD_COLOR)

    scale = size / max(width, height)
    resized = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), PAD_COLOR)
    canvas.paste(resized, ((size - resized.size[0]) // 2, (size - resized.size[1]) // 2))
    return canvas


class Letterbox:
    """`letterbox` as a torchvision-composable transform."""

    def __init__(self, size: int):
        self.size = size

    def __call__(self, image):
        return letterbox(image.convert("RGB"), self.size)

    def __repr__(self) -> str:
        return f"Letterbox(size={self.size})"


def eval_transform(image_size: int):
    """Validation and inference. Identical in both, which is the whole point of this module."""
    from torchvision import transforms

    return transforms.Compose([
        Letterbox(image_size),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])


class RandomBoxJitter:
    """Perturb the crop window the way a detector's box is imprecise.

    Geometric augmentation has to happen BEFORE letterboxing, on the original image. Letterboxing
    first and then running `RandomResizedCrop` crops into the padding — the model spends much of
    training looking at grey bars, and a first attempt built that way scored 72.2% on detector
    crops against 79.3% for the model it was meant to replace.

    Jittering the window instead reproduces the error the detector actually makes: a box slightly
    too tight, slightly too loose, slightly off-centre. Aspect ratio is left to fall where it may,
    because that is what varies in real boxes.
    """

    def __init__(self, max_scale: float = 0.18, max_shift: float = 0.10):
        self.max_scale = max_scale
        self.max_shift = max_shift

    def __call__(self, image):
        import random

        width, height = image.size
        if width < 8 or height < 8:
            return image
        grow_x = random.uniform(-self.max_scale, self.max_scale) * width
        grow_y = random.uniform(-self.max_scale, self.max_scale) * height
        shift_x = random.uniform(-self.max_shift, self.max_shift) * width
        shift_y = random.uniform(-self.max_shift, self.max_shift) * height
        left = max(0, int(-grow_x + shift_x))
        top = max(0, int(-grow_y + shift_y))
        right = min(width, int(width + grow_x + shift_x))
        bottom = min(height, int(height + grow_y + shift_y))
        if right - left < 8 or bottom - top < 8:
            return image
        return image.crop((left, top, right, bottom))

    def __repr__(self) -> str:
        return f"RandomBoxJitter(max_scale={self.max_scale}, max_shift={self.max_shift})"


def train_transform(image_size: int):
    """Training augmentation.

    Order matters: jitter the window on the original image, THEN letterbox. See `RandomBoxJitter`
    for what happened when it was done the other way round.

    Vertical flips and aggressive hue shifts stay absent, as before — they produce images that do
    not occur, and a model taught about them learns a world it will never be deployed in.
    """
    from torchvision import transforms

    return transforms.Compose([
        RandomBoxJitter(),
        Letterbox(image_size),
        transforms.RandomHorizontalFlip(),
        transforms.RandomApply([transforms.RandomRotation(12, fill=PAD_COLOR)], p=0.4),
        transforms.ColorJitter(brightness=0.25, contrast=0.25, saturation=0.15, hue=0.02),
        transforms.RandomApply([transforms.GaussianBlur(3, sigma=(0.1, 1.2))], p=0.15),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])


def transforms_for(image_size: int) -> Tuple[object, object]:
    """(train, evaluate), in the order the training script expects."""
    return train_transform(image_size), eval_transform(image_size)
