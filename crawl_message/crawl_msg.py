import re
import time
import xml.etree.ElementTree as ET

import cv2
import easyocr
import numpy as np
import uiautomator2 as u2

from utils.config import Config
from utils.helper import (find_recycler_view, is_bounds_inside_image,
                          parse_bounds, setup_logging)

log = setup_logging()
CFG = Config()

# Regex nhận diện thời gian
TIMESTAMP_RE = re.compile(r"(?i)^((TH\s\d|CN|T\d|HÔM\sNAY|HÔM\sQUA|\d{1,2}\sTHG\s\d{1,2})\s+LÚC\s+)?\d{1,2}[:\.]\d{2}$")

# Regex làm sạch thời gian trong nội dung OCR
CLEAN_TIME_RE = re.compile(r"(?i)((TH\s\d|CN|T\d|HÔM\sNAY|HÔM\sQUA|\d{1,2}\sTHG\s\d{1,2})\s+LÚC\s+)?\d{1,2}[:\.]\d{2}")

log.info("Ket noi thiet bi qua uiautomator2...")
d = u2.connect()

log.info("Dang tai model OCR (doi ti)...")
reader = easyocr.Reader(list(CFG.ocr_langs))


# ==========================================
# CÁC HÀM LOGIC CỐT LÕI MỚI
# ==========================================

def clean_messy_text(text):
    """
    Làm sạch text rác của Facebook.
    Input: "Thị Bình, hello", "hello Đã gửi", "Ảnh đại diện..."
    Output: "hello"
    """
    if not text: return ""

    # 1. Bỏ qua nếu là metadata ảnh/sticker mà không có nội dung
    if text.startswith("Ảnh đại diện") and len(text) < 25:
        return "[Hình ảnh/Sticker]"

    # 2. Xóa trạng thái cuối câu (Đã gửi, Đã xem...)
    # Regex tìm: khoảng trắng + Đã gửi/đã xem ở cuối dòng
    text = re.sub(r"(?i)(\s+(Đ|đ)ã gửi|\s+.*?(Đ|đ)ã xem|\s+.*?(Đ|đ)ã bày tỏ.*?)$", "", text)

    # 3. Xóa tên người gửi ở đầu câu (Dạng: "Tên, Nội dung")
    # Logic: Tìm dấu phẩy đầu tiên.
    match = re.match(r"^([^,]+),\s+(.*)$", text)
    if match:
        name_part = match.group(1)
        content_part = match.group(2)
        # Giả sử tên người < 40 ký tự. Nếu dài hơn thì có thể là câu văn bình thường.
        if len(name_part) < 40:
            return content_part.strip()

    return text.strip()

def determine_sender_and_clean_text(item_node, screen_width):
    """
    Hàm 2-trong-1: Vừa xác định người gửi, vừa lấy text sạch nhất.
    """
    # Tìm node con chứa text (TextView) bên trong item
    text_node = None
    raw_text = ""

    # Ưu tiên tìm node có attribute 'text' (thường sạch hơn content-desc)
    for child in item_node.iter():
        t = child.attrib.get('text', '').strip()
        if t:
            text_node = child
            raw_text = t
            break

    # Nếu không có text, tìm content-desc
    if not text_node:
        for child in item_node.iter():
            desc = child.attrib.get('content-desc', '').strip()
            if desc:
                text_node = child
                raw_text = desc
                break

    # Nếu không tìm thấy node chữ nào -> Dùng chính item cha
    target_node = text_node if text_node is not None else item_node

    # --- XÁC ĐỊNH NGƯỜI GỬI ---
    bounds_str = target_node.attrib.get("bounds")
    l, t, r, b = parse_bounds(bounds_str)

    # Logic: Nếu lề trái (Left) của khối CHỮ lớn hơn 20% màn hình -> Nằm lệch phải -> ME
    # Nếu lề trái nhỏ (gần sát mép trái) -> THEM
    sender = "THEM"
    if l > (screen_width * 0.2):
        sender = "ME"  # Page

    # --- LÀM SẠCH TEXT ---
    final_text = clean_messy_text(raw_text)

    return sender, final_text, (l, t, r, b)


# ==========================================
# SCAN & CRAWL
# ==========================================

def scan_current_screen_messages() -> list:
    messages_in_view = []

    try:
        full_screenshot = d.screenshot(format="opencv")
        screen_h, screen_w = full_screenshot.shape[:2]
        xml_content = d.dump_hierarchy()
        root = ET.fromstring(xml_content)
    except Exception:
        return []

    recycler_view = find_recycler_view(root)
    if not recycler_view:
        return []

    items = list(recycler_view)

    for index, item in enumerate(items):
        try:
            bounds_str = item.attrib.get("bounds")
            i_l, i_t, i_r, i_b = parse_bounds(bounds_str)
            if (i_b - i_t) < 20: continue

            # 1. Lấy thông tin sơ bộ từ XML
            # sender_xml: Sender dự đoán từ XML (có thể sai nếu XML rỗng)
            sender_xml, xml_text, text_bounds = determine_sender_and_clean_text(item, screen_w)

            # Tọa độ dự kiến để cắt ảnh
            ocr_l, ocr_t, ocr_r, ocr_b = text_bounds
            # Fallback nếu bounds text lỗi
            if (ocr_r - ocr_l) < 10:
                ocr_l, ocr_t, ocr_r, ocr_b = i_l, i_t, i_r, i_b

            need_ocr = False

            # Kiểm tra xem có cần OCR không
            if not xml_text:
                need_ocr = True
            elif TIMESTAMP_RE.match(xml_text):
                need_ocr = True

            final_msg = ""
            final_sender = sender_xml # Mặc định dùng sender từ XML

            if not need_ocr:
                final_msg = xml_text
                # Nếu có text từ XML, vị trí Text Node là chuẩn -> sender_xml là chuẩn
            else:
                # --- OCR LOGIC & RE-CHECK SENDER ---
                if ocr_l >= 0 and ocr_t >= 0 and ocr_r <= screen_w and ocr_b <= screen_h:
                    crop_img = full_screenshot[ocr_t:ocr_b, ocr_l:ocr_r]
                    try:
                        # detail=1: Trả về [ [box, text, conf], ... ]
                        ocr_results = reader.readtext(crop_img, detail=1)

                        full_ocr_text_parts = []

                        # Biến để tính toán vị trí trung bình của các chữ tìm được
                        total_center_x = 0
                        count_text_blocks = 0

                        for res in ocr_results:
                            # res = ([[x1,y1],[x2,y2],[x3,y3],[x4,y4]], "nội dung", conf)
                            box, text, conf = res
                            full_ocr_text_parts.append(text)

                            # Tính tọa độ X trung tâm của khối chữ trong ảnh crop
                            # box[0][0] là x_top_left, box[1][0] là x_top_right
                            block_center_x = (box[0][0] + box[1][0]) / 2
                            total_center_x += block_center_x
                            count_text_blocks += 1

                        full_ocr = " ".join(full_ocr_text_parts).strip()

                        # Clean kết quả OCR
                        temp = CLEAN_TIME_RE.sub("", full_ocr).strip()
                        final_msg = clean_messy_text(temp)

                        # --- QUAN TRỌNG: TÍNH LẠI SENDER DỰA TRÊN OCR ---
                        # Nếu OCR tìm thấy chữ, ta sẽ biết chính xác chữ đó nằm ở đâu
                        if final_msg and count_text_blocks > 0:
                            # Tọa độ X trung bình trong ảnh crop
                            avg_local_x = total_center_x / count_text_blocks

                            # Tọa độ X tuyệt đối trên màn hình
                            global_center_x = ocr_l + avg_local_x

                            # Kiểm tra lại: Lệch phải hay lệch trái?
                            if global_center_x > (screen_w / 2):
                                final_sender = "ME"
                            else:
                                final_sender = "THEM"

                    except Exception as e:
                        # Nếu lỗi OCR thì giữ nguyên sender dự đoán ban đầu
                        pass

            if final_msg:
                messages_in_view.append({
                    "sender": final_sender, # Dùng sender đã được verify
                    "content": final_msg,
                    "y_pos": i_t
                })

        except Exception:
            pass

    messages_in_view.sort(key=lambda x: x["y_pos"])
    return messages_in_view


def merge_lists_with_overlap(old_list, new_list):
    """Gộp 2 list tránh trùng lặp mép nối"""
    if not old_list: return new_list
    if not new_list: return old_list

    suffix = old_list[-5:]

    def is_same(m1, m2):
        return m1['content'] == m2['content'] and m1['sender'] == m2['sender']

    for i in range(len(new_list)):
        if is_same(suffix[-1], new_list[i]):
            if i < 4:
                return old_list + new_list[i+1:]

    return old_list + new_list

def crawl_history_with_scroll(scroll_times=2) -> list:
    log.info(f"BAT DAU CRAWL ({scroll_times + 1} man hinh)")
    pages_data = []

    for i in range(scroll_times + 1):
        log.info(f"Dang quet man hinh {i+1}...")
        msgs = scan_current_screen_messages()
        pages_data.append(msgs)
        log.info(f"   -> Lay duoc {len(msgs)} tin.")

        if i < scroll_times:
            log.info("Scroll rong de lay tin cu...")
            # Swipe rộng hơn (15% -> 85%)
            d.swipe(0.5, 0.15, 0.5, 0.85)
            time.sleep(2.5)

    full_history = []
    # Gộp ngược từ Quá khứ -> Hiện tại
    for page_msgs in reversed(pages_data):
        full_history = merge_lists_with_overlap(full_history, page_msgs)

    # Output sạch
    result = [{"sender": m["sender"], "content": m["content"]} for m in full_history]

    log.info(f"HOAN THANH. Tong: {len(result)} tin.")
    return result
