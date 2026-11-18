# Kết quả khảo sát CareerViet

Ngày khảo sát: 17/11/2026; cập nhật theo thông tin người dùng cung cấp ngày 18/11/2026 (giờ Việt Nam).

## Phạm vi và độ tin cậy

Khảo sát phục vụ thiết kế crawler tương thích với `src/crawlers/base.py`, schema raw trong `context gốc/Schema dữ liệu.md` và đề bài. Nguồn bằng chứng bên dưới là các trang CareerViet do công cụ tìm kiếm/web trả về. Một số trang là bản lưu từ những thời điểm khác nhau, vì vậy số lượng tin và nội dung có thể đã thay đổi. Không xem số kết quả tìm kiếm là số tin hợp lệ, duy nhất, còn hiệu lực hoặc đủ để đạt quy mô đề bài.

Đã đối chiếu các trang chi tiết do công cụ web trả về và tiếp nhận thông tin, hai ảnh Network do người dùng cung cấp. Trợ lý chưa quan sát trực tiếp DOM hoặc tự thao tác trình duyệt trên CareerViet, chưa chạy crawler CareerViet. Các URL mẫu dùng để đối chiếu, không phải tập dữ liệu đã cào.

## 1. Tìm kiếm và bộ keyword

| Keyword | Bằng chứng công khai tìm thấy | Trạng thái |
|---|---|---|
| Data Science | Người dùng tìm kiếm và cung cấp [trang kết quả](https://careerviet.vn/viec-lam/data-science-k-vi.html) và [trang 2](https://careerviet.vn/viec-lam/data-science-k-trang-2-vi.html). | Đã có bằng chứng người dùng thao tác thực tế; trợ lý chưa kiểm chứng trực tiếp trang 2. |
| Data Analytics | Có [trang kết quả lọc CNTT](https://careerviet.vn/viec-lam/data-analytics-kc1-vi.html); bản kết quả tìm kiếm và bản mở trang trả về dữ liệu ở các thời điểm khác nhau. | Có kết quả lưu; chưa đối chiếu hành vi hiện tại. |
| AI | Có [trang kết quả AI](https://careerviet.vn/viec-lam/ai-k-sortscore-vi.html); bản tìm thấy từ tháng 9/2026. | Có kết quả lưu; chưa kiểm tra tìm kiếm trực tiếp. |
| Machine Learning | Có [trang kết quả Machine Learning](https://careerviet.vn/viec-lam/machine-learning-k-vi.html); bản tìm thấy từ tháng 9/2026. | Có kết quả lưu; chưa kiểm tra tìm kiếm trực tiếp. |
| DevOps / Cloud | Người dùng tìm cả cụm và cung cấp [trang kết quả](https://careerviet.vn/viec-lam/devops--cloud-k-vi.html). | Theo người dùng, kết quả không đủ để có trang 2 ở thời điểm thử; chưa có số lượng cụ thể. Không tự đổi bộ keyword hoặc suy ra tổng số tin của hai từ khóa riêng. |
| Python | Có [trang kết quả Python](https://careerviet.vn/viec-lam/PYTHON-k-vi.html), bản mở được từ tháng 10/2026. | Có kết quả lưu; chưa kiểm tra tìm kiếm trực tiếp. |
| SQL | Có [trang kết quả SQL](https://careerviet.vn/viec-lam/SQL-k-vi.html), bản mở được từ tháng 10/2026. | Có kết quả lưu; chưa kiểm tra tìm kiếm trực tiếp. |
| PyTorch | Công cụ tìm kiếm trả về [trang PyTorch](https://careerviet.vn/viec-lam/pytorch-k-vi.html) với 12 tin trong bản thu thập ngày khảo sát. | Chỉ là kết quả lưu; chưa thao tác tìm kiếm trực tiếp. |

Trang [Data Analyst](https://careerviet.vn/viec-lam/data-analyst-k-vi.html) có ô tìm kiếm chức danh/kỹ năng/tên công ty và các chế độ sắp xếp. Trong cùng bản lưu có cả các vị trí Legal Staff và Senior Backend Developer. Do đó khớp từ khóa trong kết quả tìm kiếm chưa đủ để xác nhận tin thuộc phạm vi Data/AI. Số 158 trên trang là số CareerViet hiển thị tại bản lưu, không phải số tin hợp lệ đã kiểm chứng.

## 2. Phân trang và tải động

- Người dùng cho biết kết quả tìm kiếm Data Science có phân trang qua URL, không cuộn vô tận trong lần thử. Trang đầu là `/viec-lam/data-science-k-vi.html`, sau khi sang trang 2 là `/viec-lam/data-science-k-trang-2-vi.html`. Đây là quan sát của người dùng đối với mẫu đó, chưa xác nhận các keyword khác hoặc quy tắc kết thúc/URL trang cuối.
- Công cụ web mở được bản lưu trang 1 nhưng chưa mở được URL trang 2 hoặc kết quả `devops--cloud` do người dùng cung cấp. Bằng chứng người dùng quan sát trình duyệt và bản lưu từ công cụ web được ghi riêng.
- Một [bản lưu trang Data Analyst cũ](https://careerviet.vn/viec-lam/Data-Analyst--k-vi.html) hiển thị các liên kết trang 1, 2, 3, 4. Liên kết trang 2 từ bản này hết thời gian chờ khi mở. Một [URL trang 2 viết thường khác](https://careerviet.vn/viec-lam/data-analyst-k-trang-2-vi.html) trả về bản lưu tháng 7/2026. Đây là bằng chứng về phân trang trong bản lưu cũ, chưa xác nhận cơ chế trang hiện tại.
- Hai ảnh Network có bật bộ lọc `/api/` và loại `Fetch/XHR`. Ảnh hiển thị nhiều request XHR/Fetch, một số status 200/201/204. Theo [tài liệu Chrome DevTools](https://developer.chrome.com/docs/devtools/network/reference/), ô lọc có thể khớp URL, domain, hostname hoặc port. Ảnh chỉ hiển thị tên rút gọn, cần đối chiếu `Headers > General > Request URL` và phương thức của từng request.
- Người dùng đã kiểm tra một dòng `detail`: `POST https://internal-api.careerviet.vn/api/v1/js/jsk/ai-matching/detail`, status 201. Tên đường dẫn gợi ý tính năng AI matching, nhưng chưa có bằng chứng về dữ liệu trả về, mục đích chính xác, tác dụng phụ hay mức độ cần thiết để hiển thị JD. Không tự phát lại request POST này.
- Người dùng đã kiểm tra thêm một dòng `public`: `GET https://internal-api.careerviet.vn/api/v1/cs/param-config/on_off_box_ontop/public`, status 200. Tên đường dẫn gợi ý đây là cấu hình hiển thị, nhưng chưa xem nội dung phản hồi và chưa biết chức năng chính xác hoặc nó có cần thiết để hiển thị JD. Cả hai request đã xác định đều thuộc tên miền con `internal-api.careerviet.vn`.
- Việc URL thay đổi khi phân trang không chứng minh dữ liệu được đưa vào HTML ban đầu hay không có AJAX. Chưa xác định được request nào là bắt buộc để tải danh sách/JD, và chưa thể kết luận selector hoặc tín hiệu dừng.
- Khi kiểm thử kỹ thuật trên nguồn, crawler site phải hiện thực phân trang hoặc tải thêm thực tế, chờ đúng nội dung sẵn sàng và áp dụng delay ngẫu nhiên. `BaseCrawler.visit()` đã có delay, timeout và kiểm tra HTTP cho điều hướng do nó quản lý; thao tác click/cuộn tải thêm vẫn cần site crawler gọi `pause()` và xử lý điều kiện chờ.

## 3. Trang chi tiết và ánh xạ schema raw

Các mẫu:

1. [Data Analyst tại CareerViet](https://careerviet.vn/vi/tim-viec-lam/data-analyst.35C8C4F3.html) có chức danh, công ty, lương `Cạnh tranh`, hình thức, cấp bậc, kinh nghiệm, ngày cập nhật, địa điểm, phúc lợi, mô tả, yêu cầu và các thẻ từ khóa. Thông tin bên trong yêu cầu còn chứa mục quyền lợi.
2. [Data Analyst (Tableau) tại HCI Group](https://careerviet.vn/vi/tim-viec-lam/data-analyst-tableau.35C8D283.html) có các khối mô tả, yêu cầu, phúc lợi; lương xuất hiện cả trong nội dung và mục thông tin khác. Bản web trích xuất không hiển thị rõ đầu trang đầy đủ, cần xem DOM/trình duyệt trước khi xác định selector.
3. [Production Data Analyst Leader tại Fleming Việt Nam](https://careerviet.vn/vi/tim-viec-lam/production-data-analyst-leader.35C8DF41.html) có mô tả, yêu cầu, phúc lợi, địa điểm và lương `Cạnh tranh`. Bản web trích xuất không hiển thị rõ đầu trang đầy đủ.
4. Người dùng đã mở [Data Engineer tại MSB](https://careerviet.vn/vi/tim-viec-lam/data-engineer-msb-kcn-3i142.35C84663.html) và xác nhận có mô tả, yêu cầu, phúc lợi. Bản trích xuất web cũng hiển thị mô tả và yêu cầu; đó là bản lưu, không thay thế quan sát của người dùng.

| Trường raw | Nhận định từ mẫu |
|---|---|
| `title`, `company` | Có trong mẫu 1 và thông tin liên kết trang mẫu 2–3. Cần xác nhận phần tử trong trang chi tiết thực tế. |
| `location` | Có thông tin địa điểm; ít nhất một kết quả danh sách hiển thị nhiều tỉnh. Lưu nguyên văn thay vì chỉ lấy địa điểm đầu tiên. |
| `salary_raw` | Có cả `Cạnh tranh` lẫn lương dạng khoảng. Lưu chính xác giá trị nguồn; không suy ra lương số từ nhãn không có số. |
| `experience_raw` | Mẫu 1 có trường kinh nghiệm riêng. Nội dung yêu cầu còn có kinh nghiệm diễn đạt khác; giữ nguyên văn cả hai phần tương ứng, không tự hòa giải. |
| `description`, `requirements`, `benefits` | Có các tiêu đề hoặc khối liên quan trong mẫu. Quyền lợi có thể xuất hiện trong khối yêu cầu và cả khối phúc lợi riêng; giữ nội dung nguồn, không cắt bỏ. |
| `skills_raw` | Mẫu có thẻ `JOB TAGS / SKILLS` hoặc `Từ khoá / Kỹ năng`. Một số thẻ là tên vị trí hoặc thuật ngữ tìm kiếm, nên không mặc nhiên xem mọi thẻ là kỹ năng bắt buộc. |
| `employment_type_raw` | Mẫu 1 có `Hình thức: Nhân viên chính thức`; cần kiểm tra nghĩa từng nguồn trước khi quy ước giá trị. |
| `posted_at_raw` | Mẫu có **ngày cập nhật**, chưa thấy bằng chứng đó là ngày đăng. Không tự gán ngày cập nhật thành ngày đăng. |
| `work_model_raw` | Chưa xác nhận trường riêng trong ba bản trích xuất. |
| `Level` | Trang có thể hiển thị cấp bậc riêng, trong khi schema raw hiện tại chưa có cột riêng cho cấp bậc. Cần kiểm tra xem chứng cứ cấp bậc có nằm trong tiêu đề/JD trước khi quyết định có cần bổ sung schema. |

Không suy rộng tỉ lệ thiếu dữ liệu hay tính khả dụng của tất cả trường từ các mẫu. Cần đo trên mẫu crawler thực tế.

## 4. URL, mã tin và trùng lặp

- Ba URL chi tiết đã quan sát có phần mã sau dấu chấm trước `.html`, lần lượt `35C8C4F3`, `35C8D283`, `35C8DF41`. Đây là ứng viên cho `source_id`, chưa chứng minh được tính ổn định khi đổi tiêu đề, URL, phiên bản trang hoặc đăng lại.
- URL Data Engineer người dùng cung cấp có cùng dạng với mã cuối `35C84663`. Công cụ web cũng trả cùng URL khi mở liên kết Data Engineer từ bản lưu danh sách Data Science. Chưa có kết quả người dùng tải lại trang hoặc so sánh cùng tin ở các keyword, vì vậy chưa kết luận tính ổn định và quy tắc chống trùng từ riêng ví dụ này.
- Hai kết quả cùng chức danh/mã nội bộ doanh nghiệp nhưng ngày cập nhật/hạn nộp khác nhau xuất hiện trong một [bản kết quả Data Analytics](https://careerviet.vn/viec-lam/data-analytics-kc1-vi.html). Chưa đủ căn cứ khẳng định là một tin trùng; cần so sánh mã tin CareerViet và nội dung.
- `BaseCrawler` có thể nhận mã ở danh sách hoặc từ `parse_job()`, thêm tiền tố `careerviet:` và lưu `page.url` sau điều hướng làm `URL_Goc`. Cần xác nhận URL cuối thực sự là trang tin, không phải trang đăng nhập, trang gợi ý hoặc trang tin hết hạn.
- Chưa kiểm tra được cùng một tin qua nhiều keyword, các biến thể URL hoặc điều hướng trang thật. Chưa có quy tắc tin trùng giữa các nền tảng.

## 5. Robots, điều khoản và điều kiện truy cập

- Cập nhật ngày 18/11/2026: người dùng đã mở [robots.txt](https://careerviet.vn/robots.txt) và cung cấp nội dung trong cuộc trò chuyện. Công cụ web của trợ lý chưa mở được trực tiếp tệp này, do đó đây là bản do người dùng cung cấp, chưa được đối chiếu độc lập.
- Bản người dùng cung cấp cho phép `/` đối với một số bot được nêu tên, gồm `Googlebot`, `Bingbot`, `GPTBot` và `ClaudeBot`; chặn toàn bộ `/` đối với một số bot khác, gồm `CCBot`, `Amazonbot`, `Bytespider` và `Diffbot`.
- Đối với crawler tự viết có tên không khớp nhóm bot riêng, áp dụng nhóm `User-agent: *`. Bản cung cấp không chặn toàn bộ trang đối với nhóm này, nhưng có `Disallow` cho `/api/*`, `/vi/jobs/*`, `/en/jobs/*`, các đường dẫn lưu/ứng tuyển, tìm hồ sơ ứng viên và một số đường dẫn khác. Danh sách đầy đủ nằm trong nội dung người dùng đã cung cấp, cần đọc lại robots.txt hiện hành trước khi chạy.
- Theo bản cung cấp, hai đường dẫn mẫu `/viec-lam/data-analyst-k-vi.html` và `/vi/tim-viec-lam/data-analyst.35C8C4F3.html` không khớp các mục `Disallow` trong nhóm `*`. Kết luận này chỉ áp dụng cho đúng hai URL ví dụ, không mặc nhiên áp dụng cho URL sau chuyển hướng, các trang khác hoặc các yêu cầu API mà trình duyệt có thể phát sinh. Việc so khớp phải dùng đúng nhóm và đường dẫn theo [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html).
- Hai URL Data Science và URL Data Engineer người dùng vừa cung cấp cũng không khớp các `Disallow` thuộc nhóm `*` trong bản robots người dùng cung cấp. Điều này không cho biết nội dung trang phụ thuộc vào request nào hoặc cho phép mặc nhiên các request khác.
- **Phạm vi tên miền:** request `detail` người dùng cung cấp thuộc `internal-api.careerviet.vn`, khác host `careerviet.vn`. Theo [tài liệu robots.txt của Google](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec#file-location-and-range-of-validity), robots.txt được áp dụng theo host, protocol và port. Do đó không thể lấy dòng `Disallow: /api/*` của host chính để kết luận quy tắc robots của tên miền con. Công cụ web không mở được `https://internal-api.careerviet.vn/robots.txt`; chưa biết quy tắc thực tế của host đó.
- Nhóm `GPTBot` hay `Googlebot` không đại diện cho crawler của nhóm. `BaseCrawler` hiện không đặt `user_agent` riêng, không đọc hay kiểm tra robots.txt tự động; `pause()` chỉ tạo khoảng nghỉ. Không nên giả danh bot khác.
- [Điều khoản sử dụng dành cho ứng viên](https://careerviet.vn/vi/jobseekers/use) liệt kê trong mục sử dụng bị cấm việc dùng hoặc thử dùng một số công cụ/thiết bị để điều hướng hoặc tìm kiếm CareerViet, bao gồm trình thu thập dữ liệu và người máy, cùng các ngoại lệ được nêu trong điều khoản. [Bản tiếng Anh](https://careerviet.vn/en/jobseekers/use) cũng nêu spiders/robots và ngoại lệ cho trình duyệt web phổ biến và công cụ của công ty.
- **Đánh giá thận trọng:** câu chữ này có thể ảnh hưởng trực tiếp đến crawler Playwright tự viết. Chưa có xác nhận của CareerViet về việc thu thập tự động cho bài tập. Delay, robots.txt hay tính công khai của trang không tự giải quyết phạm vi điều khoản; nên làm rõ với CareerViet/người có thẩm quyền.
- Người dùng đã quan sát các trang mẫu và ảnh Network; chưa có bằng chứng đủ để kết luận về CAPTCHA, yêu cầu đăng nhập cho toàn bộ chức năng, chặn IP hay giới hạn tốc độ. Không khẳng định việc chạy crawler sẽ thành công.

## 6. Thử luồng crawler và đối chiếu CSV

**Chưa thực hiện.** Chưa có crawler CareerViet. Chín kiểm thử dữ liệu giả và thử Chromium với trang giả của `BaseCrawler` đã được thực hiện ở bước trước; các kiểm thử đó không kiểm chứng CareerViet.

Khi triển khai và kiểm thử crawler site, mẫu giới hạn cần bao gồm: tìm kiếm, qua trang kế tiếp/tải thêm theo thực tế, ít nhất vài tin chi tiết, URL và mã tin, các trường raw/cột thiếu, tiếng Việt và xuống dòng, loại trùng trong một lần chạy, tin hết hạn, lỗi và CSV đối chiếu với trang nguồn. Kiểm tra số tin thực tế theo từng keyword và số tin phù hợp sau lọc trước khi ước lượng khả năng đạt yêu cầu quy mô.

## Trở ngại khảo sát trình duyệt

- Yêu cầu kích hoạt và đọc cửa sổ Chrome đang hiển thị Google One bị cơ chế duyệt tự động từ chối do nguy cơ lộ nội dung tài khoản cá nhân không liên quan đến khảo sát. Không có kết quả từ cửa sổ đó.
- Để kiểm tra giao diện trực tiếp, cần một tab CareerViet do người dùng mở sẵn và cho phép thao tác, hoặc người dùng cung cấp thông tin quan sát được. Người dùng đã cung cấp nội dung robots.txt, như ghi ở mục 5.
- Các kết quả còn thiếu được đánh dấu rõ ở từng mục. Phạm vi áp dụng điều khoản của nhà cung cấp vẫn chưa được xác nhận.
