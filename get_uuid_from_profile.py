import uiautomator2 as u2
import time
import re
import easyocr
import cv2

d = u2.connect()
print("-> Đang tải model OCR...")
reader = easyocr.Reader(['en']) # Link chỉ cần tiếng Anh là đủ đọc

# Kết nối thiết bị

# --- PHẦN 1: ĐIỀU HƯỚNG (Mở đến bảng copy link) ---

print("Bắt đầu điều hướng...")
# 1. Click vào chữ (i) hoặc tên người dùng
# (Dùng exists để tránh lỗi nếu không tìm thấy)
if d(description="Chi tiết chuỗi bài").exists:
    d(description="Chi tiết chuỗi bài").click()
else:
    # Dự phòng nếu không thấy description
    d(resourceId="com.facebook.orca:id/thread_title_name").click()

time.sleep(4) # Chờ chuyển cảnh

# 2. Click vào nút "Trang cá nhân" (Icon Profile)
# XPath của bạn giữ nguyên, nhưng cần chờ nó xuất hiện
try:
    d.xpath('//android.widget.HorizontalScrollView/android.view.ViewGroup[1]/android.view.ViewGroup[3]').click()
    time.sleep(4) # Chờ load trang cá nhân (mạng lag thì tăng lên)
except Exception as e:
    print(f"Lỗi bước 2: {e}")

# 3. Click vào nút mở popup (nút 3 chấm hoặc nút Khác)
# XPath của bạn giữ nguyên
print("Mở popup liên kết...")
try:
    d.xpath('//*[@resource-id="android:id/content"]/android.widget.FrameLayout[1]/android.widget.LinearLayout[1]/android.widget.FrameLayout[1]/android.widget.LinearLayout[1]/android.widget.LinearLayout[1]/android.view.View[1]').click()
    time.sleep(3) # QUAN TRỌNG: Chờ popup hiện lên mới tính tọa độ được
except Exception as e:
    print(f"Lỗi bước 3: {e}")


# --- PHẦN 2: XỬ LÝ CLICK THEO TỌA ĐỘ ---

def click_copy_link_relative():
    print("Đang quét popup...")
    
    # CHIẾN THUẬT:
    # Vì cả cái bảng là 1 khối, ta tìm khối đó dựa vào Text đặc trưng bên trong nó.
    # Text đặc trưng ở đây là: "Liên kết đến trang cá nhân" hoặc "facebook.com"
    
    elem = d(textContains="Liên kết riêng của")
    
    # Nếu không tìm thấy bằng text tiếng Việt, thử tìm bằng link
    if not elem.exists:
        elem = d(textContains="facebook.com")
        
    # Nếu tìm thấy khối đó
    if elem.exists:
        # Lấy vùng tọa độ (rect) của cả khối
        bounds = elem.info['bounds']
        top = bounds['top']
        bottom = bounds['bottom']
        left = bounds['left']
        right = bounds['right']
        
        # Tính chiều rộng và chiều cao của khối
        width = right - left
        height = bottom - top
        
        print(f"Đã bắt được khung popup: Rộng={width}, Cao={height}")
        print(f"Vị trí: {bounds}")

        # --- TÍNH TOÁN ĐIỂM CLICK ---
        # Nút "Sao chép liên kết" thường nằm ở đáy và giữa.
        # X = Lấy điểm giữa chiều ngang (left + 50% rộng)
        # Y = Lấy điểm gần đáy (top + 85% cao)
        
        click_x = left + (width * 0.5)
        click_y = top + (height * 0.85)
        
        print(f"--> Thực hiện click tại: ({click_x}, {click_y})")
        d.click(click_x, click_y)
        
        # Chờ 1 chút để clipboard hệ thống kịp nhận
        time.sleep(1)
        
        # Lấy dữ liệu từ Clipboard
        try:
            link_data = d.clipboard
            print("--------------------------------")
            print(f"LINK LẤY ĐƯỢC: {link_data}")
            print("--------------------------------")
            return link_data
        except Exception as e:
            print(f"Không lấy được clipboard: {e}")
            return None
            
    else:
        print("Lỗi: Không tìm thấy khung popup chứa chữ 'Liên kết đến trang cá nhân'")
        # Debug: In ra xml để xem nó đang tên là gì nếu code fail
        # with open("debug_ui.xml", "w", encoding='utf-8') as f:
        #     f.write(d.dump_hierarchy())
        return None

def get_facebook_id_via_ocr():
    print("--- BẮT ĐẦU QUÉT ID TỪ POPUP ---")
    start_time = time.time()
    
    # 1. Tìm cái khung popup
    # Tìm theo text đặc trưng có trong popup
    elem = d(textContains="Liên kết riêng của")
    
    # Nếu không tìm thấy bằng text tiếng Việt, thử tìm bằng link
    if not elem.exists:
        elem = d(textContains="facebook.com")
        
    if elem.exists:
        # Lấy tọa độ
        bounds = elem.info['bounds']
        left, top, right, bottom = bounds['left'], bounds['top'], bounds['right'], bounds['bottom']
        
        # Chụp và cắt ảnh
        screenshot = d.screenshot(format='opencv')
        if left < 0: left = 0
        if top < 0: top = 0
        crop_img = screenshot[top:bottom, left:right]
        
        # 2. OCR
        print("-> Đang đọc chữ trong popup...")
        result = reader.readtext(crop_img, detail=0)
        full_text = " ".join(result)
        print(f"-> Text thô OCR: {full_text}")
        
        # --- PHẦN SỬA ĐỔI QUAN TRỌNG: REGEX LINH HOẠT ---
        
        # Giải thích Regex mới:
        # facebook[\s\.]*com  -> Tìm chữ facebook, sau đó là dấu chấm HOẶC dấu cách (xử lý lỗi OCR mất dấu chấm)
        # [\s\/]+             -> Tìm dấu gạch chéo / HOẶC dấu cách (xử lý lỗi OCR https:I/ )
        # (.*?)               -> Lấy toàn bộ nội dung phía sau (Group 1)
        # (?=\sSao|\s*$)      -> Dừng lại khi gặp chữ " Sao" (của nút Sao chép) hoặc hết dòng.
        
        pattern = r"facebook[\s\.]*com[\s\/]+(.*?)(?=\sSao|\s*$)"
        
        match = re.search(pattern, full_text, re.IGNORECASE)
        
        final_id = None
        
        if match:
            raw_id = match.group(1) # Lấy được: "nguyen.van.chien .753743"
            
            # 3. LÀM SẠCH ID (Xóa hết dấu cách thừa do OCR thêm vào)
            final_id = raw_id.replace(" ", "").strip()
            
            # Xóa dấu chấm ở cuối nếu có (nguyen.van.chien.)
            final_id = final_id.rstrip(".")
            
        else:
            # Fallback cho trường hợp link là id=...
            match_uid = re.search(r"id[\s=]+(\d+)", full_text)
            if match_uid:
                final_id = match_uid.group(1)
                
        total_time = time.time() - start_time

        # --- KẾT QUẢ ---
        if final_id:
            print("--------------------------------")
            print(f"ID DATABASE CHUẨN: {final_id}")
            print("--------------------------------")
            jump_to_chat_by_id(final_id)
            return final_id
        else:
            print("Không tìm thấy ID (Regex không khớp).")
            return None
    else:
        print("Lỗi: Không tìm thấy popup.")
        return None
    

def jump_to_chat_by_id(user_id,message="hihi"):
    """
    Hàm này dùng Deep Link để nhảy thẳng vào đoạn chat với user_id
    Bất chấp đang đứng ở màn hình nào.
    """
    print(f"Đang nhảy tới khung chat của: {user_id}")
    
    # URL Deep Link của Messenger
    url = f"https://m.me/{user_id}"
    
    # Lệnh Shell: Yêu cầu mở URL này bằng app Messenger (com.facebook.orca)
    # Việc chỉ định gói com.facebook.orca giúp tránh việc nó mở bằng Chrome
    cmd = f'am start -a android.intent.action.VIEW -d "{url}" com.facebook.orca'
    d.shell(cmd)
    
    # Chờ Messenger xử lý và load UI
    print("Đang chờ Messenger load giao diện chat...")
    
    input_xpath = '//*[@text="Nhắn tin"]'
    
    if d.xpath(input_xpath).wait(timeout=15):
        print("Đã vào khung chat (Thấy ô Nhắn tin).")
        time.sleep(1)
        
        # 3. CLICK VÀ NHẬP TEXT
        print(f"[2/3] Đang nhập: '{message}'")
        
        # Click vào ô "Nhắn tin" để bàn phím hiện lên
        d.xpath(input_xpath).click()
        time.sleep(1)
        
        # Nhập nội dung
        d.send_keys(message)
        time.sleep(1) # Chờ nút gửi hiện ra
        
        # 4. TÌM NÚT GỬI
        print("[3/3] Đang bấm Gửi...")
        
        # Ưu tiên 1: Tìm nút có description là "Gửi"
        if d(description="Gửi").exists:
            d(description="Gửi").click()
        # Ưu tiên 2: Tìm nút "Send" (tiếng Anh)
        elif d(description="Send").exists:
            d(description="Send").click()
        # Ưu tiên 3: Nếu không tìm thấy nút Gửi trên UI -> Bấm Enter bàn phím
        else:
            print("Không thấy nút Gửi -> Bấm Enter trên bàn phím.")
            d.press("enter")
            
        print(f"HOÀN TẤT GỬI TIN CHO {user_id}")
        return True
            
    else:
        print("Lỗi: Chờ 15s vẫn không thấy ô 'Nhắn tin'.")
        # Debug: In ra cấu trúc màn hình hiện tại xem nó đang kẹt ở đâu
        # print(d.dump_hierarchy())
        return False

# Chạy hàm
get_facebook_id_via_ocr()