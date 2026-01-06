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
import time
import xml.etree.ElementTree as ET

import easyocr
import uiautomator2 as u2

from crawl_message.crawl_msg import crawl_history_with_scroll
from utils.config import Config
from utils.helper import (find_recycler_view, get_all_text_from_node_recursive,
                          get_facebook_id_via_ocr, is_bounds_inside_image,
                          jump_to_chat_by_id, navigate_to_profile_popup,
                          parse_bounds, send_messages, setup_logging)

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
    # --- BƯỚC 1: Lấy UUID trước (từ profile popup)
    if not navigate_to_profile_popup(d, log):
        log.error("Không thể điều hướng tới popup để lấy UUID. Dừng luồng.")
        return

    user_id = get_facebook_id_via_ocr(d, reader, log)
    if not user_id:
        log.error("Không lấy được UUID. Dừng luồng.")
        return

        # Đợi chat load
    time.sleep(5)

    # --- BƯỚC 2: NHẢY VÀO KHUNG CHAT (BẮT BUỘC TRƯỚC KHI CRAWL) ---
    # Phải vào chat thì mới thấy tin nhắn để crawl
    if not jump_to_chat_by_id(d, user_id, log):
        log.error("Không thể nhảy vào khung chat. Dừng luồng.")
        return

    # Chờ load lịch sử chat cũ
    time.sleep(3)


    # --- BƯỚC 3: Đọc tin nhắn (Crawl 2-3 màn hình)
    # scroll_times=2 nghĩa là lấy màn hình hiện tại + scroll lên 2 lần nữa (Tổng 3 màn hình)
    history_data = crawl_history_with_scroll(scroll_times=2)
    # In kết quả ra console để kiểm tra
    print("\n" + "="*40)
    print(f"HỘI THOẠI VỚI: {user_id}")
    print("="*40)
    for msg in history_data:
        role = "Khách" if msg['sender'] == "THEM" else "Page "
        print(f"[{role}]: {msg['content']}")
    print("="*40 + "\n")

    # --- BƯỚC 4: GỬI TIN NHẮN (LOGIC TRẢ LỜI) ---
    # Ví dụ: Nếu khách hỏi giá, gửi báo giá. Ở đây demo gửi list tin.

    log.info("Bắt đầu gửi tin nhắn phản hồi...")
    send_success = send_messages(
        d,
        log,
        messages=["hello", "xin chao", "da crawl xong history", "bye bye"],
        delay_between_sends_s=0.5
    )

    if not send_success:
        log.error("Gửi tin nhắn thất bại.")

    # Đợi xíu trước khi kết thúc
    time.sleep(2)

if __name__ == "__main__":
    main()
