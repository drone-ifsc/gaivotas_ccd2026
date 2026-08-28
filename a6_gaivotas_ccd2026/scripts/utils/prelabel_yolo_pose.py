#!/usr/bin/env python3
"""Pre-annotate images with a YOLO-pose model -> Label Studio predictions JSON.

Model-in-the-loop labeling: run a trained YOLO11-pose model (center + 4 corners)
over a folder of images and emit a Label Studio tasks file with ``predictions``, so
you only *correct* the points instead of placing them from scratch.

Keypoint 0 -> label 'center', keypoints 1..4 -> label 'corner'.
Matches this project's LS config (from_name='kp', to_name='image', percent coords).

Usage:
    python3 prelabel_yolo_pose.py \
        --model ../ai_models/pesocomcameradrone.pt \
        --images /path/to/new_images \
        --out prelabel_tasks.json \
        --url-prefix '/data/local-files/?d=new_images/'

Then in Label Studio: Project -> Import -> prelabel_tasks.json.
The images must be reachable by LS at each task's ``data.image`` URL:
  * Local file serving: start LS with LOCAL_FILES_SERVING_ENABLED=true and use
    --url-prefix '/data/local-files/?d=<subdir>/'  (subdir under LOCAL_FILES_DOCUMENT_ROOT).
  * HTTP/cloud:         --url-prefix 'https://host/path/'.
Predictions appear pre-filled; accept or drag to fix, then submit.

Runs in any env with ultralytics + opencv (e.g. the ROS container that runs base_reader).
"""
import argparse
import glob
import json
import os

import cv2
from ultralytics import YOLO

IMG_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')


def kps_to_result(kps, kconf, W, H, from_name, to_name, kpt_conf):
    """Build LS keypointlabels items. kps:(K,2) px, kconf:(K,) or None.

    Keypoint 0 is the center; 1..4 are corners. Undetected (0,0) or low-confidence
    keypoints are skipped so the human adds them instead of fixing a wrong guess.
    """
    result = []
    for i in range(len(kps)):
        x, y = float(kps[i][0]), float(kps[i][1])
        if x <= 0 and y <= 0:
            continue
        if kconf is not None and float(kconf[i]) < kpt_conf:
            continue
        label = 'center' if i == 0 else 'corner'
        result.append({
            'from_name': from_name,
            'to_name': to_name,
            'type': 'keypointlabels',
            'original_width': W,
            'original_height': H,
            'image_rotation': 0,
            'value': {
                'x': x / W * 100.0,          # LS stores coords as percent
                'y': y / H * 100.0,
                'width': 0.5,
                'keypointlabels': [label],
            },
        })
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', required=True, help='YOLO-pose .pt weights')
    ap.add_argument('--images', required=True, help='folder with images to pre-label')
    ap.add_argument('--out', default='prelabel_tasks.json', help='output LS tasks json')
    ap.add_argument('--conf', type=float, default=0.5, help='detection confidence threshold')
    ap.add_argument('--kpt-conf', type=float, default=0.3, help='per-keypoint confidence threshold')
    ap.add_argument('--imgsz', type=int, default=640, help='inference image size')
    ap.add_argument('--from-name', default='kp', help="LS control tag name (from_name)")
    ap.add_argument('--to-name', default='image', help="LS object tag name (to_name)")
    ap.add_argument('--url-prefix', default='', help='prepended to each image basename for data.image')
    ap.add_argument('--model-version', default='yolo-pose-prelabel')
    args = ap.parse_args()

    model = YOLO(args.model, task='pose')
    paths = sorted(p for p in glob.glob(os.path.join(args.images, '**', '*'), recursive=True)
                   if p.lower().endswith(IMG_EXT))
    print(f'{len(paths)} images in {args.images}')

    tasks, n_pred, n_empty = [], 0, 0
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            print('  skip (unreadable):', p)
            continue
        H, W = img.shape[:2]
        res = model(img, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]

        task = {'data': {'image': args.url_prefix + os.path.basename(p)}}
        if res.boxes is not None and len(res.boxes) and res.keypoints is not None:
            best = int(res.boxes.conf.argmax())      # single base per image -> best box
            kps = res.keypoints.xy[best].cpu().numpy()
            kconf = (res.keypoints.conf[best].cpu().numpy()
                     if res.keypoints.conf is not None else None)
            result = kps_to_result(kps, kconf, W, H, args.from_name, args.to_name, args.kpt_conf)
            if result:
                task['predictions'] = [{
                    'model_version': args.model_version,
                    'score': float(res.boxes.conf[best]),
                    'result': result,
                }]
                n_pred += 1
            else:
                n_empty += 1
        else:
            n_empty += 1
        tasks.append(task)

    with open(args.out, 'w') as f:
        json.dump(tasks, f, indent=2)
    print(f'wrote {args.out}: {len(tasks)} tasks  ({n_pred} pre-labeled, {n_empty} without points)')


if __name__ == '__main__':
    main()
