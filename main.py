# import uiautomator2 as u2
# import xml.etree.ElementTree as ET
# import re
# import cv2
# import easyocr

# # --- KHỞI TẠO ---
# d = u2.connect()

# # Load model OCR (chỉ load 1 lần để đỡ lag)
# print("-> Đang tải model OCR (đợi tí)...")
# reader = easyocr.Reader(['vi', 'en'])

# # --- CẤU HÌNH REGEX ---
# # Regex nhận diện thời gian (để check xem có phải chỉ có mỗi giờ không)
# TIMESTAMP_REGEX = r"(?i)^((TH\s\d|CN|T\d|HÔM\sNAY|HÔM\sQUA|\d{1,2}\sTHG\s\d{1,2})\s+LÚC\s+)?\d{1,2}:\d{2}$"

# # Regex dùng để XÓA thời gian ra khỏi kết quả OCR (để lấy nội dung tin nhắn)
# # Nó tương tự cái trên nhưng không bắt buộc phải nằm ở đầu/cuối chuỗi
# CLEAN_TIME_REGEX = r"(?i)((TH\s\d|CN|T\d|HÔM\sNAY|HÔM\sQUA|\d{1,2}\sTHG\s\d{1,2})\s+LÚC\s+)?\d{1,2}:\d{2}"

# def parse_bounds(bounds_str):
#     if not bounds_str: return (0,0,0,0)
#     matches = re.findall(r'\d+', bounds_str)
#     if len(matches) == 4:
#         return tuple(map(int, matches))
#     return (0,0,0,0)

# def get_all_text_from_node_recursive(node):
#     texts = []
#     t = node.attrib.get('text', '')
#     d_text = node.attrib.get('content-desc', '')
#     if t: texts.append(t)
#     if d_text and d_text != t: texts.append(d_text)

#     for child in node.iter():
#         ct = child.attrib.get('text', '')
#         cdesc = child.attrib.get('content-desc', '')
#         if ct and ct not in texts: texts.append(ct)
#         if cdesc and cdesc not in texts and cdesc != ct: texts.append(cdesc)

#     return " ".join(texts).strip()

# def process_messages_complete():
#     print("--- BẮT ĐẦU QUÉT & OCR ---")

#     # 1. Chụp màn hình TỔNG (format opencv để cắt cho dễ)
#     # Lưu ý: Chụp trước khi dump xml để đảm bảo đồng bộ
#     full_screenshot = d.screenshot(format='opencv')

#     # 2. Lấy XML
#     xml_content = d.dump_hierarchy()
#     root = ET.fromstring(xml_content)

#     recycler_view = None
#     for elem in root.iter():
#         if "RecyclerView" in elem.attrib.get('class', ''):
#             recycler_view = elem
#             break

#     if not recycler_view:
#         print("Không thấy khung chat.")
#         return

#     items = list(recycler_view)

#     for index, item in enumerate(items):
#         try:
#             bounds_str = item.attrib.get('bounds')
#             left, top, right, bottom = parse_bounds(bounds_str)
#             width, height = right - left, bottom - top

#             if height < 40: continue

#             # Lấy text từ XML
#             xml_text = get_all_text_from_node_recursive(item)

#             need_ocr = False
#             reason = ""

#             # --- LOGIC QUYẾT ĐỊNH OCR ---
#             if not xml_text:
#                 need_ocr = True
#                 reason = "Không có text (Ảnh/Sticker/Flatten)"
#             elif re.match(TIMESTAMP_REGEX, xml_text):
#                 need_ocr = True
#                 reason = f"Chỉ có Timestamp ({xml_text})"

#             # --- XỬ LÝ ---
#             if need_ocr:
#                 print(f"[Index {index}] CẦN GỌI OCR ({reason})")

#                 # 1. Kiểm tra tọa độ hợp lệ
#                 if left < 0 or top < 0 or right > full_screenshot.shape[1] or bottom > full_screenshot.shape[0]:
#                     print("    -> Tọa độ lỗi, bỏ qua cắt ảnh.")
#                     continue

#                 # 2. CẮT ẢNH (Cực kỳ quan trọng: [y:y+h, x:x+w])
#                 # Tức là [top:bottom, left:right]
#                 crop_img = full_screenshot[top:bottom, left:right]

#                 # 3. GỌI EASYOCR
#                 # detail=0 chỉ trả về list text
#                 ocr_results = reader.readtext(crop_img, detail=0)
#                 full_ocr_text = " ".join(ocr_results)

#                 print(f"-> OCR Gốc: {full_ocr_text}")

#                 # 4. LÀM SẠCH (Tách bỏ phần ngày giờ để lấy tin nhắn)
#                 # Thay thế phần ngày giờ bằng chuỗi rỗng
#                 final_msg = re.sub(CLEAN_TIME_REGEX, "", full_ocr_text).strip()

#                 print(f"    -> TIN NHẮN CUỐI CÙNG: {final_msg}")

#             else:
#                 print(f"[Index {index}] TXT CHUẨN: {xml_text}")

#         except Exception as e:
#             print(f"Lỗi {index}: {e}")

# # --- CHẠY ---
# process_messages_complete()

import re
import xml.etree.ElementTree as ET
import time

import easyocr
import uiautomator2 as u2


from utils.config import Config
from utils.helper import (
    setup_logging,
    parse_bounds,
    get_all_text_from_node_recursive,
    find_recycler_view,
    is_bounds_inside_image,
    navigate_to_profile_popup,
    get_facebook_id_via_ocr,
    jump_to_chat_by_id,
)
from crawl_message.crawl_msg import process_messages_complete

log = setup_logging()
CFG = Config()

# Pre-compile regex (nhanh + gọn)
TIMESTAMP_RE = re.compile(CFG.timestamp_regex)
CLEAN_TIME_RE = re.compile(CFG.clean_time_regex)

log.info("Kết nối thiết bị qua uiautomator2...")
d = u2.connect()

# =========================
# INIT
# =========================
log.info("Đang tải model OCR (đợi tí)...")
reader = easyocr.Reader(list(CFG.ocr_langs))


# =========================
# ENTRYPOINT
# =========================
def main() -> None:
    # 1) Lấy UUID trước (từ profile popup)
    if not navigate_to_profile_popup(d, log):
        log.error("Không thể điều hướng tới popup để lấy UUID. Dừng luồng.")
        return

    user_id = get_facebook_id_via_ocr(d, reader, log)
    if not user_id:
        log.error("Không lấy được UUID. Dừng luồng.")
        return

    # 2) Nhắn tin
    if not jump_to_chat_by_id(
        d,
        user_id,
        log,
        messages=["hello", "xin chao", "tin 3", "alo alo", "toi dayyy"],
    ):
        log.error("Nhảy chat/gửi tin thất bại. Dừng luồng.")
        return

    # Đợi chat load
    time.sleep(5)

    # 3) Đọc tin nhắn (OCR theo logic hiện tại)
    process_messages_complete()


if __name__ == "__main__":
    main()
