import uiautomator2 as u2
import time
d = u2.connect()
  
def left_group(d, group_link):
  """
  Hàm rời nhóm Facebook
  """
  print(f"Bat dau roi nhom: {group_link}")

  # 1. Dieu huong
  full_link = f"https://www.facebook.com/{group_link}"
  d.shell(f"am start -a android.intent.action.VIEW -d '{full_link}'")
  
  print("Dang cho load trang nhom...")
  time.sleep(5)

  # 2. Tim nut "Da tham gia"
  # Dùng textContains để bắt dính bất kể tên nhóm là gì
  joined_btn = d(textContains="tham gia")
  
  if not joined_btn.exists:
      joined_btn = d(descriptionContains="tham gia")

  if joined_btn.exists:
      print("Da tim thay nut trang thai 'Da tham gia'. Click...")
      joined_btn.click()
      time.sleep(2) 
  else:
      print("Khong thay nut 'Da tham gia'. Co the chua vao nhom hoac UI khac.")
      return False

  # 3. Chon "Roi nhom" trong menu
  # Bắt đầu bằng chữ "Rời nhóm" để bỏ qua phần mô tả dài phía sau
  leave_option = d(textStartsWith="Rời nhóm")
  
  if not leave_option.exists:
      leave_option = d(textStartsWith="Leave group")

  if leave_option.exists:
      print("Chon tuy chon 'Roi nhom'...")
      leave_option.click()
      time.sleep(2) 
  else:
      print("Khong thay tuy chon Roi nhom trong menu.")
      return False

  # 4. Xac nhan Rời (Popup)
  # Tìm nút RỜI NHÓM viết hoa
  confirm_btn = d(text="RỜI NHÓM")
  
  if not confirm_btn.exists:
      # ID thường gặp của nút OK/Confirm bên phải trong Android
      confirm_btn = d(resourceId="com.facebook.katana:id/button1") 
  
  if not confirm_btn.exists:
      confirm_btn = d(text="LEAVE GROUP")

  if confirm_btn.exists:
      confirm_btn.click()
      time.sleep(3)
      return True
  else:
      print("Khong tim thay nut xac nhan cuoi cung.")
      return False

