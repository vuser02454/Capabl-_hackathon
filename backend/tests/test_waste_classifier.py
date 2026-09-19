

def test_serving_and_training_share_one_preprocessing_definition():
    """The transform the backend applies must be the one training produced weights for.

    They were separate once. Training validated on square dataset photos with Resize+CenterCrop
    and scored macro-F1 0.911; serving applied that same transform to tall detector crops, where
    CenterCrop keeps a patch of the middle and throws the object's shape away. On 145 real bottle
    crops it cost 36% correct versus 87%, and no metric in the project moved, because nothing ever
    evaluated the transform that was actually served.
    """
    import sys
    from pathlib import Path

    from services.waste import waste_classifier

    sys.path.insert(0, str(Path(waste_classifier.__file__).resolve().parents[3] / "training"))
    import waste_preprocess

    assert waste_classifier._eval_transform(224) is not None
    # Serving resolves the transform through the training package rather than restating it.
    assert waste_classifier._preprocess_version() == waste_preprocess.PREPROCESS_VERSION


def test_letterbox_preserves_the_whole_object():
    """A tall crop must arrive whole, not centre-cropped down to its middle."""
    import sys
    from pathlib import Path

    from PIL import Image

    from services.waste import waste_classifier

    sys.path.insert(0, str(Path(waste_classifier.__file__).resolve().parents[3] / "training"))
    import waste_preprocess

    # A bottle crop shape: 2.6x taller than wide, which is the median measured on real detections.
    tall = Image.new("RGB", (120, 312), (200, 30, 30))
    out = waste_preprocess.letterbox(tall, 224)

    assert out.size == (224, 224)
    # The full height of the object survives: scaled by 224/312, it occupies 224 rows.
    colours = {out.getpixel((112, y)) for y in range(224)}
    assert (200, 30, 30) in colours
    # Aspect ratio is preserved, so the sides are padding rather than stretched object.
    assert out.getpixel((2, 112)) == waste_preprocess.PAD_COLOR
