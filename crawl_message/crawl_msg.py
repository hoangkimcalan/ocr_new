import re
import xml.etree.ElementTree as ET

import easyocr
import uiautomator2 as u2

from utils.config import Config
from utils.helper import (
    setup_logging,
    parse_bounds,
    get_all_text_from_node_recursive,
    find_recycler_view,
    is_bounds_inside_image,
    pick_message_bubble_bounds,
    classify_message_side_by_bounds,
)
log = setup_logging()
CFG = Config()

TIMESTAMP_RE = re.compile(CFG.timestamp_regex)
CLEAN_TIME_RE = re.compile(CFG.clean_time_regex)

log.info("Kết nối thiết bị qua uiautomator2...")
d = u2.connect()

log.info("Đang tải model OCR (đợi tí)...")
reader = easyocr.Reader(list(CFG.ocr_langs))


def process_messages_complete() -> None:
    log.info("BẮT ĐẦU QUÉT & OCR")

    try:
        full_screenshot = d.screenshot(format="opencv")
    except Exception as e:
        log.exception("Không chụp được screenshot: %s", e)
        return

    screen_h, screen_w = full_screenshot.shape[:2]

    try:
        xml_content = d.dump_hierarchy()
        root = ET.fromstring(xml_content)
    except Exception as e:
        log.exception("Không đọc/parse được UI hierarchy: %s", e)
        return

    recycler_view = find_recycler_view(root)
    if not recycler_view:
        log.warning("Không thấy khung chat (RecyclerView).")
        return

    items = list(recycler_view)
    log.info("Tìm thấy %d item trong RecyclerView.", len(items))

    for index, item in enumerate(items):
        try:
            # bounds của item (chỉ để filter theo height)
            bounds_str = item.attrib.get("bounds")
            i_l, i_t, i_r, i_b = parse_bounds(bounds_str)
            i_h = i_b - i_t
            if i_h < CFG.min_item_height_px:
                continue

            # bounds của bubble (để classify + crop OCR)
            bubble = pick_message_bubble_bounds(item, screen_width=screen_w)
            if not bubble:
                log.debug("Index %d: không pick được bubble bounds -> skip", index)
                continue

            left, top, right, bottom = bubble
            side = classify_message_side_by_bounds(left, right, screen_w)

            # Text từ XML: vẫn lấy theo item (vì có thể text nằm sâu)
            xml_text = get_all_text_from_node_recursive(item)

            need_ocr = False
            reason = None
            if not xml_text:
                need_ocr = True
                reason = "Không có text (Ảnh/Sticker/Flatten)"
            elif TIMESTAMP_RE.match(xml_text):
                need_ocr = True
                reason = f"Chỉ có Timestamp ({xml_text})"

            if not need_ocr:
                log.info("Index %d [%s]: TXT CHUẨN: %s", index, side, xml_text)
                continue

            log.info("Index %d [%s]: CẦN GỌI OCR (%s)", index, side, reason)

            if not is_bounds_inside_image(left, top, right, bottom, full_screenshot):
                log.warning(
                    "Index %d [%s]: bubble bounds lỗi/outside image: %s (img=%sx%s) -> bỏ qua",
                    index,
                    side,
                    bubble,
                    screen_w,
                    screen_h,
                )
                continue

            crop_img = full_screenshot[top:bottom, left:right]

            try:
                ocr_results = reader.readtext(crop_img, detail=0)
            except Exception as e:
                log.exception("Index %d [%s]: OCR lỗi: %s", index, side, e)
                continue

            full_ocr_text = " ".join(ocr_results).strip()
            final_msg = CLEAN_TIME_RE.sub("", full_ocr_text).strip()

            if final_msg:
                log.info("Index %d [%s]: MSG: %s", index, side, final_msg)
            else:
                log.info(
                    "Index %d [%s]: OCR rỗng sau khi clean timestamp.", index, side
                )

        except Exception as e:
            log.exception("Index %d: lỗi xử lý item: %s", index, e)
