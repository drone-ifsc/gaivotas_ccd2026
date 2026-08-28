#!/usr/bin/env python3
"""Label Studio JSON export -> YOLO-pose dataset (5 keypoints: center + 4 corners).

Why this exists: Label Studio's *YOLO* export cannot represent this project's
keypoints. The base has 5 physical points (1 center + 4 corners) but only 2
label names ('center', 'corner'); YOLO-pose needs one unique label per slot, so
LS drops every keypoint (exports bboxes with all-zero kpts). The *JSON* export
keeps the real points, so we convert from JSON instead.

Corner ordering: the 4 corners share the label 'corner', so they have no stored
order. We assign each corner to a fixed slot by its image quadrant relative to
the center -> consistent slots across images:

    slot 0 = center
    slot 1 = top-left      (x<cx, y<cy)      # y grows downward in image coords
    slot 2 = top-right     (x>cx, y<cy)
    slot 3 = bottom-right  (x>cx, y>cy)
    slot 4 = bottom-left   (x<cx, y>cy)

Partial annotations (some corners missing) are handled naturally: a missing
quadrant stays (0,0) visibility=0 and YOLO's pose loss ignores it. Downstream
base_reader uses corner *distances* (order-invariant), so slot noise near 45deg
rotation is harmless. flip_idx swaps L<->R corners for horizontal-flip aug.

The per-instance bbox is derived from the enclosing box of the present
keypoints plus a small margin (LS keypoint-only projects have no rectangle).

Usage:
    python3 ls_json_to_yolo_pose.py \
        --json /path/to/project-6-....json \
        --images /path/to/images_dir \
        --out ../../dataset/yolo_pose \
        --val-frac 0.15 --seed 0
"""
import argparse
import json
import math
import os
import random
import shutil

KPT_NAMES = ["center", "corner_tl", "corner_tr", "corner_br", "corner_bl"]
FLIP_IDX = [0, 2, 1, 4, 3]  # h-flip: TL<->TR, BL<->BR; center fixed
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def task_image_name(t):
    fu = t.get("file_upload")
    if fu:
        return fu
    return os.path.basename(t.get("data", {}).get("image", ""))


def collect_keypoints(task):
    """Return (center_xy, corners_list) in FRACTION coords [0,1], or (None, []).

    LS stores x/y as percent (0-100) with per-result original_width/height.
    """
    center = None
    corners = []
    for ann in task.get("annotations", []):
        for r in ann.get("result", []):
            if r.get("type") != "keypointlabels":
                continue
            v = r["value"]
            x = v["x"] / 100.0
            y = v["y"] / 100.0
            label = v["keypointlabels"][0]
            if label == "center":
                if center is None:
                    center = (x, y)
            else:
                corners.append((x, y))
    return center, corners


def assign_corner_slots(center, corners):
    """Map each corner to a fixed slot (1..4) by quadrant around the center.

    Returns list of 5 (x, y, vis) triplets: slot0=center, slots1..4 corners.
    Missing corners -> (0, 0, 0). Quadrant collisions -> nearest free slot.
    """
    cx, cy = center
    slots = [None] * 5
    slots[0] = (cx, cy, 2)

    # quadrant -> slot index (image coords, y down)
    def quad_slot(x, y):
        left = x < cx
        top = y < cy
        if left and top:
            return 1  # TL
        if (not left) and top:
            return 2  # TR
        if (not left) and (not top):
            return 3  # BR
        return 4      # BL

    for (x, y) in corners:
        s = quad_slot(x, y)
        if slots[s] is None:
            slots[s] = (x, y, 2)
        else:
            # collision: place in the nearest still-free corner slot by angle
            free = [i for i in (1, 2, 3, 4) if slots[i] is None]
            if not free:
                continue
            ang = math.atan2(y - cy, x - cx)
            # canonical slot angles (y down): TL,TR,BR,BL
            canon = {1: math.atan2(-1, -1), 2: math.atan2(-1, 1),
                     3: math.atan2(1, 1), 4: math.atan2(1, -1)}
            s2 = min(free, key=lambda i: abs(math.atan2(
                math.sin(ang - canon[i]), math.cos(ang - canon[i]))))
            slots[s2] = (x, y, 2)

    return [s if s is not None else (0.0, 0.0, 0) for s in slots]


def kpts_to_bbox(kpts, margin=0.06):
    """Enclosing box (cx, cy, w, h) in fractions from visible kpts + margin."""
    pts = [(x, y) for (x, y, v) in kpts if v > 0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    w = (x1 - x0)
    h = (y1 - y0)
    # pad relative to box size (with a small absolute floor for tiny boxes)
    px = max(w * margin, 0.01)
    py = max(h * margin, 0.01)
    x0 = max(0.0, x0 - px); x1 = min(1.0, x1 + px)
    y0 = max(0.0, y0 - py); y1 = min(1.0, y1 + py)
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    return cx, cy, (x1 - x0), (y1 - y0)


def clamp01(v):
    return min(1.0, max(0.0, v))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", required=True, help="Label Studio JSON export")
    ap.add_argument("--images", required=True, help="folder with the exported images")
    ap.add_argument("--out", required=True, help="output YOLO dataset dir")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--copy-images", action="store_true", default=True,
                    help="copy images into the dataset (default). Use --no-copy to symlink")
    ap.add_argument("--no-copy", dest="copy_images", action="store_false")
    args = ap.parse_args()

    tasks = json.load(open(args.json))
    img_files = {f: os.path.join(args.images, f) for f in os.listdir(args.images)
                 if f.lower().endswith(IMG_EXT)}

    rows = []          # (img_name, label_lines)
    n_kept = n_skip_noimg = n_skip_nocenter = 0
    slot_hist = {1: 0, 2: 0, 3: 0, 4: 0}
    for t in tasks:
        name = task_image_name(t)
        if name not in img_files:
            n_skip_noimg += 1
            continue
        center, corners = collect_keypoints(t)
        if center is None:
            n_skip_nocenter += 1
            continue
        kpts = assign_corner_slots(center, corners)
        for i in (1, 2, 3, 4):
            if kpts[i][2] > 0:
                slot_hist[i] += 1
        cx, cy, w, h = kpts_to_bbox(kpts)
        flat = [f"{clamp01(cx):.6f}", f"{clamp01(cy):.6f}",
                f"{clamp01(w):.6f}", f"{clamp01(h):.6f}"]
        for (x, y, v) in kpts:
            flat += [f"{clamp01(x):.6f}", f"{clamp01(y):.6f}", str(int(v))]
        rows.append((name, "0 " + " ".join(flat)))
        n_kept += 1

    # split
    random.seed(args.seed)
    random.shuffle(rows)
    n_val = max(1, int(round(len(rows) * args.val_frac)))
    val = rows[:n_val]
    train = rows[n_val:]

    # write dataset tree
    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)

    def emit(split, items):
        for name, line in items:
            src = img_files[name]
            dst = os.path.join(args.out, "images", split, name)
            if args.copy_images:
                shutil.copy2(src, dst)
            else:
                if os.path.lexists(dst):
                    os.remove(dst)
                os.symlink(os.path.abspath(src), dst)
            stem = os.path.splitext(name)[0]
            with open(os.path.join(args.out, "labels", split, stem + ".txt"), "w") as f:
                f.write(line + "\n")

    emit("train", train)
    emit("val", val)

    yaml_path = os.path.join(args.out, "data.yaml")
    with open(yaml_path, "w") as f:
        f.write(
            "# Generated by ls_json_to_yolo_pose.py — landing base, 5 keypoints\n"
            f"path: {os.path.abspath(args.out)}\n"
            "train: images/train\n"
            "val: images/val\n"
            "kpt_shape: [5, 3]\n"
            f"flip_idx: {FLIP_IDX}\n"
            "names:\n"
            "  0: base_pouso\n"
        )

    print(f"kept {n_kept} images  (train {len(train)} / val {len(val)})")
    print(f"skipped: no-image {n_skip_noimg}, no-center {n_skip_nocenter}")
    print(f"corner slot coverage (of {n_kept}): "
          f"TL {slot_hist[1]}  TR {slot_hist[2]}  BR {slot_hist[3]}  BL {slot_hist[4]}")
    print(f"wrote {args.out}  (data.yaml, kpt_shape [5,3], flip_idx {FLIP_IDX})")


if __name__ == "__main__":
    main()
