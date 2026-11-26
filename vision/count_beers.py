"""
Count beers in photos with a zero-shot (text-prompted) object detector.

    python vision/count_beers.py detect --model owlv2 [--tiles]
    python vision/count_beers.py evaluate --model owlv2 [--tiles]

`detect` runs the model once over data/beer_images and caches every detection
(low threshold) to vision/cache/<model>[-tiled].json. With --tiles it also runs
on four overlapping zoomed-in quarters of each photo, for small far-away glasses. `evaluate` sweeps score threshold
and counting rule over the cache, tuning on half of the captioned photos and
reporting on the other half, with the "+N" captions as ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "data" / "beer_images"
CACHE = Path(__file__).resolve().parent / "cache"

# prompt -> group; a bottle/can poured into a glass is one beer (see `max` rule).
# "decoy" prompts are never counted: they exist to win NMS on water, shots, soda, wine.
PROMPTS = {
    "a glass of beer": "glass",
    "a beer mug": "glass",
    "a beer bottle": "container",
    "a beer can": "container",
    "a glass of water": "decoy",
    "a wine glass": "decoy",
    "a shot glass": "decoy",
    "a soda can": "decoy",
}
MODELS = {
    "owlv2": "google/owlv2-base-patch16-ensemble",
    "owlv2-large": "google/owlv2-large-patch14-ensemble",
    "gdino": "IDEA-Research/grounding-dino-base",
}


def load_image(path: Path):
    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


TILE = 0.6  # each tile spans 60% of the width and height, so neighbours overlap by 20%


def tiles(w: int, h: int) -> list[tuple[int, int, int, int]]:
    """The whole photo first, then its four overlapping corner tiles."""
    tw, th = int(w * TILE), int(h * TILE)
    return [(0, 0, w, h)] + [(x, y, x + tw, y + th) for y in (0, h - th) for x in (0, w - tw)]


def cut_at_tile_edge(box: list[float], tile: tuple[int, int, int, int], w: int, h: int) -> bool:
    """A box touching a tile border that isn't the photo border shows only part of an object."""
    x0, y0, x1, y1 = tile
    m = 0.01 * max(w, h)
    return (
        (x0 > 0 and box[0] <= x0 + m) or (y0 > 0 and box[1] <= y0 + m)
        or (x1 < w and box[2] >= x1 - m) or (y1 < h and box[3] >= y1 - m)
    )


def cache_path(model_name: str, tiled: bool) -> Path:
    return CACHE / f"{model_name}{'-tiled' if tiled else ''}.json"


def detect(model_name: str, tiled: bool = False) -> None:
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    # the large model only fits an 8 GB GPU in half precision
    dtype = torch.float16 if device == "cuda" and model_name.endswith("large") else torch.float32
    processor = AutoProcessor.from_pretrained(MODELS[model_name])
    model = (
        AutoModelForZeroShotObjectDetection.from_pretrained(MODELS[model_name], dtype=dtype)
        .to(device)
        .eval()
    )
    prompts = list(PROMPTS)

    files = sorted(p.relative_to(IMAGES).as_posix() for p in IMAGES.glob("*captioned/*.*"))

    def run(image) -> tuple[list, list, list]:
        w, h = image.size
        with torch.no_grad():
            if model_name.startswith("owlv2"):
                inputs = processor(text=[prompts], images=image, return_tensors="pt").to(device, dtype=dtype)
                outputs = model(**inputs)
                side = max(w, h)  # OWLv2 pads to a square before resizing
                det = processor.post_process_object_detection(
                    outputs, threshold=0.05, target_sizes=[(side, side)]
                )[0]
                labels = [prompts[int(k)] for k in det["labels"]]
            else:
                text = ". ".join(prompts) + "."
                inputs = processor(images=image, text=text, return_tensors="pt").to(device)
                outputs = model(**inputs)
                det = processor.post_process_grounded_object_detection(
                    outputs, inputs.input_ids, threshold=0.15, text_threshold=0.15,
                    target_sizes=[(h, w)],
                )[0]
                labels = [match_prompt(t) for t in det.get("text_labels", det["labels"])]
        return [[float(v) for v in b] for b in det["boxes"]], [float(x) for x in det["scores"]], labels

    results = {}
    for i, rel in enumerate(files, 1):
        image = load_image(IMAGES / rel)
        w, h = image.size
        entry = {"size": [w, h], "boxes": [], "scores": [], "labels": []}
        for tile in tiles(w, h) if tiled else [(0, 0, w, h)]:
            boxes, scores, labels = run(image.crop(tile))
            for b, sc, lab in zip(boxes, scores, labels):
                b = [b[0] + tile[0], b[1] + tile[1], b[2] + tile[0], b[3] + tile[1]]
                if tile != (0, 0, w, h) and cut_at_tile_edge(b, tile, w, h):
                    continue
                entry["boxes"].append([round(v, 1) for v in b])
                entry["scores"].append(round(sc, 4))
                entry["labels"].append(lab)
        results[rel] = entry
        if i % 25 == 0:
            print(f"{i}/{len(files)}", flush=True)

    CACHE.mkdir(exist_ok=True)
    cache_path(model_name, tiled).write_text(json.dumps(results))
    print(f"cached {len(results)} images -> {cache_path(model_name, tiled)}")


def match_prompt(text: str) -> str:
    """Grounding DINO returns the matched phrase; map it back to one of PROMPTS."""
    words = set(text.lower().split())
    return max(PROMPTS, key=lambda p: len(words & set(p.split()) - {"a", "of"}))


def box_area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: list[float], b: list[float]) -> float:
    return box_area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def count(
    det: dict, threshold: float, rule: str, min_area: float = 0.0, ioa: float = 1.0, iou: float = 0.5
) -> int:
    """
    threshold: minimum detection score
    rule:      "sum" (glasses + bottles/cans) or "max" (a bottle and its glass are one beer)
    min_area:  minimum box area as a fraction of the photo (drops shelves/background)
    ioa:       drop a box when this fraction of it lies inside a bigger kept box
    """
    import torch
    from torchvision.ops import nms

    w, h = det["size"]
    keep = [
        i
        for i, s in enumerate(det["scores"])
        if s >= threshold and box_area(det["boxes"][i]) / (w * h) >= min_area
    ]
    if not keep:
        return 1  # it's a known beer post, so never count less than the scanner does
    boxes = torch.tensor([det["boxes"][i] for i in keep])
    scores = torch.tensor([det["scores"][i] for i in keep])
    # class-agnostic: the same object is often both "a glass of beer" and "a beer mug"
    survivors = [keep[i] for i in nms(boxes, scores, iou).tolist()]
    kept: list[int] = []
    for i in sorted(survivors, key=lambda i: -box_area(det["boxes"][i])):
        b = det["boxes"][i]
        if not any(intersection(b, det["boxes"][j]) >= ioa * box_area(b) for j in kept):
            kept.append(i)
    groups = [PROMPTS[det["labels"][i]] for i in kept]
    glasses, containers = groups.count("glass"), groups.count("container")
    return glasses + containers if rule == "sum" else max(glasses, containers, 1)


def score(pairs: list[tuple[int, int]]) -> dict:
    return {
        "exact": sum(p == c for p, c in pairs) / len(pairs),
        "within1": sum(abs(p - c) <= 1 for p, c in pairs) / len(pairs),
        "mae": statistics.mean(abs(p - c) for p, c in pairs),
        "total": sum(p for p, _ in pairs),
    }


def evaluate(model_name: str, tiled: bool = False) -> None:
    dets = json.loads(cache_path(model_name, tiled).read_text())
    labelled = [
        (r["file"], int(r["caption_plus"]))
        for r in csv.DictReader(open(IMAGES / "index.csv"))
        if r["caption_plus"] and r["file"] in dets
    ]
    tune, test = labelled[0::2], labelled[1::2]

    grid = product(
        [round(0.05 * k, 2) for k in range(2, 13)],  # threshold
        ["sum", "max"],  # rule
        [0.0, 0.005, 0.01, 0.02, 0.04],  # min_area
        [1.0, 0.8, 0.6],  # ioa
    )

    def tune_key(params):
        s = score([(count(dets[f], *params), c) for f, c in tune])
        return s["exact"], -s["mae"]

    params = max(grid, key=tune_key)
    threshold, rule, min_area, ioa = params
    print(
        f"model {model_name}: best on tune half -> threshold {threshold}, rule {rule}, "
        f"min_area {min_area}, ioa {ioa}"
    )
    for name, rows in [("tune", tune), ("test", test), ("all", labelled)]:
        s = score([(count(dets[f], *params), c) for f, c in rows])
        base = score([(1, c) for _, c in rows])
        print(
            f"  {name:4s} n={len(rows):3d}  exact {s['exact']:4.0%} (scanner {base['exact']:4.0%})  "
            f"within±1 {s['within1']:4.0%}  MAE {s['mae']:.2f}  total {s['total']} / {sum(c for _, c in rows)}"
        )

    uncaptioned = [f for f in dets if f.startswith("uncaptioned/")]
    predicted = [count(dets[f], *params) for f in uncaptioned]
    nothing_found = sum(not any(s >= threshold for s in dets[f]["scores"]) for f in dets)
    print(
        f"  uncaptioned: {len(uncaptioned)} photos -> {sum(predicted)} beers "
        f"(scanner counts {len(uncaptioned)}); photos with nothing detected: {nothing_found}/{len(dets)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["detect", "evaluate"])
    parser.add_argument("--model", choices=list(MODELS), default="owlv2")
    parser.add_argument("--tiles", action="store_true", help="also detect on zoomed-in quarters")
    args = parser.parse_args()
    if args.command == "detect":
        detect(args.model, args.tiles)
    else:
        evaluate(args.model, args.tiles)


if __name__ == "__main__":
    main()
