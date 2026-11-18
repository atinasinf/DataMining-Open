# Yêu cầu nâng cấp & sửa lỗi `src/crawlers/careerviet.py` (và `base.py`)

## 1. Bối cảnh & Lỗi thực tế từ phiên chạy thử
* **Lệnh đã chạy:** `python -m src.crawlers.careerviet` (chế độ headless, 8 từ khóa mặc định).
* **Hiện tượng:** Crawler lấy thành công 50 job ở trang 1 từ khóa `Data Science`, cào được một số tin đầu tiên nhưng sau đó sập toàn bộ tiến trình tại URL chi tiết:
  `https://careerviet.vn/vi/tim-viec-lam/hr-data-analyst.35C8B40F.html`
* **Chi tiết lỗi:**
  * `PlaywrightTimeout: Locator.wait_for: Timeout 30000ms exceeded` khi chờ selector `.job-desc-main h1.title`.
  * Exception này bị ném thành `RuntimeError` trong `CareerVietCrawler.parse_job()`, truyền ngược lên `BaseCrawler._read_row()` -> `_collect()` -> `run()`, khiến toàn bộ phiên cào bị ngắt ngang và chỉ để lại file tạm `.csv.part`.

---

## 2. Các điểm cần Codex sửa đổi

### Điểm 1 (Ưu tiên cao nhất): Hỗ trợ giao diện tuyển dụng VIP / Custom Template
* **Nguyên nhân:** Trên CareerViet, nhiều doanh nghiệp lớn sử dụng giao diện tuyển dụng thiết kế riêng (VIP/custom layout) thay vì khung HTML chuẩn của sàn. Các trang này **không có** class `.job-desc-main` hay `section.job-detail-content`, khiến lệnh `_wait_content(page, ".job-desc-main h1.title")` luôn bị timeout sau 30 giây.
* **Hướng sửa:**
  1. **Đảo thứ tự ưu tiên bóc tách:** Thay vì chờ `.job-desc-main h1.title` trước, hãy chờ và đọc thẻ `script#job-posting-schema[type="application/ld+json"]` trước tiên (vì hầu hết các trang VIP của CareerViet vẫn nhúng chuẩn schema JSON-LD `JobPosting` để làm SEO).
  2. **Bổ sung Fallback từ JSON-LD:** Nếu DOM không có `.job-desc-main` hoặc `section.job-detail-content`, tự động lấy dữ liệu dự phòng từ object JSON-LD `JobPosting`:
     * `title` <- `posting.get("title")`
     * `company` <- `posting.get("hiringOrganization", {}).get("name")`
     * `description` <- `posting.get("description")`
     * `skills_raw` <- `posting.get("skills")`
     * `employment_type_raw` <- `posting.get("employmentType")`
     * `posted_at_raw` <- `posting.get("datePosted")`
     * `location` <- trích xuất từ `posting.get("jobLocation")`
     * `salary_raw` <- trích xuất từ `posting.get("baseSalary")`
  3. **Mở rộng Selector dự phòng cho DOM:** Cập nhật `_wait_content` trong `parse_job` để chờ linh hoạt nhiều dấu hiệu nhận diện trang đã tải xong (ví dụ: `script#job-posting-schema, .job-desc-main h1.title, h1`) thay vì khóa cứng một selector duy nhất.

### Điểm 2 (Ưu tiên cao nhất): Cơ chế chịu lỗi từng tin (Fault Tolerance) thay vì sập cả mẻ cào
* **Nguyên nhân:** `BaseCrawler` đang áp dụng cơ chế *fail-fast* quá gắt ở tầng trang chi tiết: chỉ cần 1/1000 tin bị timeout hoặc layout lạ là ném `RuntimeError` dừng hẳn chương trình, dù `BaseCrawler` đã có sẵn biến thống kê `failed`.
* **Hướng sửa:**
  1. Tách bạch **lỗi hệ thống** (bị chặn IP, CAPTCHA, trang tìm kiếm đổi layout, redirect bất thường -> cần dừng hẳn) với **lỗi từng tin lẻ** (1 URL chi tiết bị timeout, tin đã hết hạn/xóa, hoặc template VIP không đọc được -> ghi log `WARNING`, tăng `result.failed += 1` và **bỏ qua để cào tiếp link kế tiếp**).
  2. Chỉ tự động dừng chương trình nếu tỷ lệ lỗi liên tiếp vượt ngưỡng an toàn (ví dụ: lỗi liên tiếp 10 tin liền nhau, chứng tỏ mạng rớt hoặc bị chặn).
  3. Đảm bảo nếu người dùng bấm `Ctrl+C` (`KeyboardInterrupt`) hoặc gặp lỗi dừng khẩn cấp, dữ liệu đã cào được vẫn được lưu an toàn và dễ phục hồi từ file `.csv.part`.

### Điểm 3 (Ưu tiên cao): Tăng tốc tải trang & Retry khi nghẽn mạng
* **Nguyên nhân:** Việc tải đầy đủ ảnh, font, banner quảng cáo và script tracking bên thứ 3 làm trang chi tiết nặng, dễ vượt quá `timeout_ms = 30000` khi treo máy dài.
* **Hướng sửa:**
  1. Trong `CareerVietCrawler.configure_context()`, ngoài việc chặn `https://careerviet.vn/api/**`, chặn thêm các tài nguyên không cần thiết cho việc cào text (`resource_type` thuộc nhóm `{"image", "media", "font"}` và các domain tracking/ads phổ biến) để trang load nhanh gấp 3–4 lần.
  2. Thêm cơ chế **Retry (thử lại 1–2 lần)** với khoảng nghỉ ngắn (2–3 giây) nếu `page.goto` hoặc `_wait_content` gặp `PlaywrightTimeout` do lag mạng nhất thời trước khi đánh dấu tin đó là `failed`.

### Điểm 4 (Ưu tiên trung bình): Hỗ trợ Resume / Bỏ qua các `source_id` đã cào
* **Nguyên nhân:** Khi chạy chia đợt theo từng `--keyword` hoặc chạy lại sau khi bị gián đoạn giữa chừng, scraper sẽ cào lại từ đầu các job đã tồn tại trong các file `.csv` / `.csv.part` trước đó.
* **Hướng sửa:**
  * Bổ sung tùy chọn CLI (ví dụ `--resume` hoặc tự động quét các file `.csv` hiện có trong `--raw-dir`) để nạp danh sách `source_id` đã thu thập vào tập `seen_ids` ngay khi khởi động, giúp bỏ qua nhanh các link đã có dữ liệu.

### Điểm 5 (Ưu tiên thấp): Cải thiện Logging khi treo máy trên Windows PowerShell
* **Nguyên nhân:** `logging.basicConfig()` mặc định đẩy toàn bộ log `INFO` ra `stderr`, khiến Windows PowerShell hiển thị thành chữ đỏ kèm lỗi giả `NativeCommandError` khi redirect luồng ghi file log.
* **Hướng sửa:**
  * Cấu hình logger xuất `INFO` ra `sys.stdout` (chỉ xuất `WARNING`/`ERROR` ra `sys.stderr`), đồng thời bổ sung tham số `--log-file` trực tiếp vào `argparse` trong `careerviet.py` để người dùng ghi log mà không cần dùng pipe của PowerShell.

---

## 3. Tiêu chí kiểm tra sau khi Codex sửa code (Acceptance Criteria)
1. Chạy test riêng với URL từng gây lỗi (`https://careerviet.vn/vi/tim-viec-lam/hr-data-analyst.35C8B40F.html`): bóc tách được dữ liệu từ JSON-LD/fallback mà không bị `TimeoutError`.
2. Giả lập 1 URL lỗi/không tồn tại trong danh sách: crawler ghi nhận `failed=1` và tiếp tục cào bình thường các tin phía sau cho đến hết, xuất ra file `.csv` hoàn chỉnh (không kẹt ở `.csv.part`).
3. Chạy thử `python -m src.crawlers.careerviet --max-jobs 20` hoàn tất mượt mà, log hiển thị sạch sẽ.