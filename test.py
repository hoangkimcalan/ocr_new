import os
import time
import re
import unicodedata
import easyocr
import cv2

READER = None

def init_reader(lang=("vi", "en"), use_gpu=True):
    global READER
    if READER is None:
        READER = easyocr.Reader(list(lang), gpu=use_gpu)
    return READER

def _rect_from_bbox(bbox):
    xs = [int(p[0]) for p in bbox]
    ys = [int(p[1]) for p in bbox]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    return x1, y1, x2, y2

def _normalize_text(s: str) -> str:
    # remove accents + uppercase
    s = (s or "").strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.upper()
    s = re.sub(r"\s+", " ", s)
    return s

_TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
def _is_date_separator(text_norm: str, center_x_ratio: float) -> bool:
    # thường nằm giữa + có "LUC" và giờ
    if not (0.35 <= center_x_ratio <= 0.65):
        return False
    has_time = bool(_TIME_RE.search(text_norm))
    has_luc = (" LUC " in f" {text_norm} ") or ("LUC" in text_norm)
    has_th = text_norm.startswith("TH ") or text_norm.startswith("T")  # TH 3, T2...
    has_hom = "HOM NAY" in text_norm or "HOM QUA" in text_norm
    return has_time and (has_luc or has_th or has_hom)

def _sender_from_center(center_x_ratio: float) -> str:
    # chỉnh ngưỡng theo UI của mày nếu cần
    if center_x_ratio >= 0.60:
        return "ME"
    if center_x_ratio <= 0.40:
        return "THEM"
    return "UNKNOWN"

def _group_by_lines(items, y_thresh=22):
    """
    items: list dict {x1,y1,x2,y2,text,conf}
    gom theo dòng dựa vào mid_y gần nhau
    """
    items = sorted(items, key=lambda it: ((it["y1"]+it["y2"])//2, it["x1"]))
    groups = []
    for it in items:
        mid_y = (it["y1"] + it["y2"]) / 2
        placed = False
        for g in groups:
            if abs(mid_y - g["mid_y"]) <= y_thresh:
                g["items"].append(it)
                # update group bbox
                g["x1"] = min(g["x1"], it["x1"])
                g["y1"] = min(g["y1"], it["y1"])
                g["x2"] = max(g["x2"], it["x2"])
                g["y2"] = max(g["y2"], it["y2"])
                # update mid_y (running average)
                g["mid_y"] = (g["mid_y"] * g["count"] + mid_y) / (g["count"] + 1)
                g["count"] += 1
                placed = True
                break
        if not placed:
            groups.append({
                "items": [it],
                "x1": it["x1"], "y1": it["y1"], "x2": it["x2"], "y2": it["y2"],
                "mid_y": mid_y,
                "count": 1
            })

    # sort each group items by x then join text
    for g in groups:
        g["items"].sort(key=lambda it: it["x1"])
        g["text"] = " ".join([it["text"].strip() for it in g["items"] if it["text"].strip()])
        g["conf"] = sum([it["conf"] for it in g["items"]]) / max(1, len(g["items"]))
    return groups

def ocr_classify(
    image_path: str,
    lang=("vi", "en"),
    use_gpu=True,
    show=True,
    save_path=None,
    min_conf=0.2,
):
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Không thấy file: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Ảnh đọc vào bị None.")

    h, w = img.shape[:2]
    reader = init_reader(lang=lang, use_gpu=use_gpu)

    t0 = time.perf_counter()
    results = reader.readtext(
        img,
        detail=1,
        paragraph=False,
        batch_size=8,
        mag_ratio=2.5,
        canvas_size=2560,
        text_threshold=0.4,
        low_text=0.3,
        link_threshold=0.4,
    )
    dt = time.perf_counter() - t0

    # convert -> items
    items = []
    for bbox, text, conf in results:
        if conf < min_conf:
            continue
        x1, y1, x2, y2 = _rect_from_bbox(bbox)
        items.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "text": text, "conf": conf})

    # group by lines (đỡ bị tách chữ)
    groups = _group_by_lines(items, y_thresh=22)

    annotated = img.copy()
    classified = []

    for g in groups:
        gx1, gy1, gx2, gy2 = g["x1"], g["y1"], g["x2"], g["y2"]
        text = g["text"]
        conf = g["conf"]

        center_x = (gx1 + gx2) / 2.0
        center_x_ratio = center_x / float(w)

        text_norm = _normalize_text(text)
        if _is_date_separator(text_norm, center_x_ratio):
            label = "DATE"
            color = (0, 255, 0)
        else:
            who = _sender_from_center(center_x_ratio)
            label = who
            color = (255, 0, 0) if who == "ME" else (0, 0, 255) if who == "THEM" else (0, 255, 255)

        classified.append({
            "label": label,
            "text": text,
            "conf": conf,
            "bbox": (gx1, gy1, gx2, gy2),
            "center_x_ratio": center_x_ratio
        })

        # draw
        cv2.rectangle(annotated, (gx1, gy1), (gx2, gy2), color, 2)

    # In kết quả
    print(f"Time: {dt:.3f}s")
    print("===== CLASSIFIED OCR =====")
    for it in classified:
        print(f"[{it['label']}] ({it['conf']:.2f}) {it['text']}")

    if save_path:
        cv2.imwrite(save_path, annotated)
        print(f"Saved annotated image to: {save_path}")

    if show:
        cv2.imshow("Classified OCR", annotated)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return classified, dt, annotated


if __name__ == "__main__":
    image_path = r"D:\cahk\python\ocr\image1.jpg"
    save_path  = r"D:\cahk\python\ocr\image1_annotated.jpg"

    classified, sec, _ = ocr_classify(
        image_path=image_path,
        lang=("vi", "en"),
        use_gpu=True,
        show=True,
        save_path=save_path,
        min_conf=0.2
    )
