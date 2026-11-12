# Stockfish 19 Pro — 5h30m Supreme Experience Dojo (GitHub Actions)

Hệ thống rèn luyện và tích lũy **Kinh Nghiệm Thực Chiến Độc Quyền (`experience.bin` + `embedded_experience_blob.h`)** cho **Stockfish 19 Pro (V7.0 Apex Singularity Edition)** trong suốt **5 giờ 30 phút (`330 phút`)** liên tục trên GitHub Actions (đa bàn song song + giải phẫu hậu chiến Depth 18-20).

## 1. Cấu trúc hệ thống
- `.github/workflows/train-experience-5h30m.yml`: Workflow GitHub Actions chạy trên `ubuntu-24.04-arm` (hoặc `ubuntu-latest`), tự động tải bản engine chuẩn từ Google Drive (`1PdgGTXNhHOwZy_39nmc4C0vmlyaF6EJO`), biên dịch `stockfish-pro` & `stockfish-sparring`, chạy rèn luyện song song nhiều bàn trong **330 phút (5h30p)** và xuất gói kết quả `Stockfish-Pro-Supreme-Experience-Bundle`.
- `scripts/setup_and_build_dojo.sh`: Script tải tự động từ Google Drive (`1PdgGTXNhHOwZy_39nmc4C0vmlyaF6EJO`), trích xuất mạng NNUE `nn-1a298aa575a0.nnue` (kể cả khi mạng nằm nhúng bên trong file thực thi ELF của Termux/Android), và biên dịch bản thực thi tối ưu cho máy chủ huấn luyện.
- `scripts/forge_experience_5h30m.py`: Trình điều phối đa luồng (Multi-Board Async Orchestrator) kết hợp **3 chế độ va chạm**:
  1. **Adversarial Crucible (`Pro vs. Sparring`)**: Đấu đối kháng trực diện qua 60 khai cuộc/gambit biến hóa để học đường phản công và diệt thế hòa.
  2. **Persona Clash (`Pro-Attacker vs. Pro-Fortress`)**: Tự va chạm nội bộ giữa hai thái cực Tấn Công Bão Táp (`Contempt=65`) và Pháo Đài Phòng Thủ (`Contempt=15`).
  3. **Deep Post-Mortem Surgery (`Depth 18–20`)**: Tự động mổ xẻ các bước ngoặt chiến thuật (`|Δeval| >= 45 cp`) ở độ sâu lớn và ghi đè nước đi tối ưu vào `experience.bin`.
- `engines/Stockfish-19-Pro-Ultimate-V3/`: Toàn bộ mã nguồn C++ lõi **Stockfish 19 Pro V7.0 Apex Singularity** kèm sẵn `2,768` thế cờ hạt nhân Depth-32.

## 2. Cách chạy trên GitHub Actions (5h30p)
1. Giải nén toàn bộ gói này và đẩy lên repository GitHub của bạn (đảm bảo thư mục `.github/workflows/train-experience-5h30m.yml`, `scripts/`, và `engines/` nằm ở thư mục gốc của repo).
2. Vào tab **Actions** trên GitHub -> chọn **Stockfish 19 Pro - 5h30m Supreme Experience Dojo** -> bấm **Run workflow**.
3. Sau 5h30p (hoặc bất cứ lúc nào bạn bấm Cancel sớm), tải Artifact **`Stockfish-Pro-Supreme-Experience-Bundle`** về `/sdcard/Download/`.

## 3. Cách nạp kinh nghiệm mới vào Stockfish Pro trên Termux
Sau khi tải `Stockfish-Pro-Supreme-Experience-Bundle.zip` về `/sdcard/Download/` và giải nén, bạn có thể:
- **Cách 1 (Dùng trực tiếp file `experience.bin`)**: Trỏ UCI option `Experience File` tới đường dẫn `experience.bin` vừa rèn xong.
- **Cách 2 (Nhúng thẳng vào ruột file thực thi Android ARM64)**: Chạy lệnh:
  ```bash
  bash /sdcard/Download/termux_inject_forged_experience.sh
  ```
