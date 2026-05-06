# Rule — Quy tắc làm việc

> Đây là rule **bắt buộc**. Áp dụng cho mọi phiên làm việc trên dự án này.

## R1. Luôn đọc 2 file này trước khi bắt đầu BẤT KỲ task nào

1. **`CLAUDE.md`** — quy tắc hành vi (think before coding, simplicity first, surgical changes, goal-driven execution).
2. **`plan.md`** — kế hoạch chính thức của dự án, gồm các phase + checkbox tiến độ.

Không có ngoại lệ. Đọc 2 file này trước khi viết code, trước khi reply user, trước khi spawn subagent.

## R2. Mọi việc thực thi PHẢI bám sát `plan.md`

- Chỉ làm việc nằm trong các Phase đã định nghĩa.
- Không tự thêm task ngoài plan. Nếu phát hiện cần task mới → **dừng lại, hỏi user, cập nhật plan.md trước khi làm**.
- Không skip phase. Hoàn thành Definition of Done của Phase N trước khi sang Phase N+1.
- Không gộp/tách phase mà không bàn với user.

## R3. Tick checkbox sau khi hoàn thành

- Khi 1 task xong → edit `plan.md`, đổi `[ ]` thành `[x]` cho đúng dòng đó.
- Khi tất cả task + verification của 1 Phase xong → tick cả Definition of Done.
- KHÔNG tick trước khi thực sự verify pass. Tick là cam kết "việc này đã hoàn thành và verified".
- Tick ngay khi xong, không gom batch — để user nhìn `plan.md` biết được tiến độ realtime.

## R4. Khi verification fail

- KHÔNG tick checkbox.
- Báo cáo ngắn gọn cho user: task nào, fail ra sao, root cause nghi ngờ.
- Đề xuất hướng fix → đợi user xác nhận trước khi sửa lớn.

## R5. Khi gặp tình huống không có trong plan

- Dừng lại. Không tự ý xử lý theo phỏng đoán.
- Trình bày tình huống cho user, đưa 2-3 phương án (kèm tradeoff).
- User quyết định → cập nhật `plan.md` (thêm task hoặc đổi phase) → tiếp tục.

## R6. Ưu tiên thứ tự khi có xung đột

Nếu hướng dẫn từ các nguồn khác nhau xung đột, áp dụng thứ tự ưu tiên:

1. **User instruction trong message hiện tại** (cao nhất)
2. **`rule.md`** (file này)
3. **`plan.md`**
4. **`CLAUDE.md`**
5. Hệ thống / memory / mặc định khác

## R7. Không làm các việc nguy hiểm

- Không `git push --force`, `git reset --hard`, `rm -rf`, drop database, delete branch... mà chưa có lệnh tường minh từ user.
- Không commit `.env`, không log API key ra stdout.
- Không xóa `data/chats.db` trừ khi user yêu cầu rõ.

## R8. Báo cáo tiến độ cuối mỗi turn

Khi kết thúc 1 turn có thay đổi:
- Liệt kê **ngắn gọn** task vừa hoàn thành (đã tick)
- Trỏ tới Phase + task tiếp theo theo `plan.md`
- Không lặp lại nội dung file đã ghi rõ — chỉ delta.

## R9. Tự kiểm tra rule sau mỗi lần xong việc

Đây là rule tự nhắc — áp dụng cuối mỗi turn có thực thi task:

1. **"Mình có đang tuân theo rule.md không?"** — nhẩm qua R1-R8.
2. **R3 check:** task vừa xong đã tick `[x]` trong `plan.md` chưa?
3. **R2 check:** mình có làm thứ gì ngoài plan không?
4. **R8 check:** mình có báo cáo ngắn gọn cuối turn không?

Nếu phát hiện vi phạm bất kỳ rule nào → **nhận ra ngay, nói thẳng với user, điều chỉnh trong cùng turn đó**. Không lặng lẽ bỏ qua.
