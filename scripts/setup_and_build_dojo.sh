#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build"
RESULTS_DIR="${REPO_ROOT}/results"
PRO_GDRIVE_ID="${PRO_GDRIVE_ID:-1PdgGTXNhHOwZy_39nmc4C0vmlyaF6EJO}"
EXPECTED_NNUE_NAME="nn-1a298aa575a0.nnue"
EXPECTED_NNUE_SHA256="1a298aa575a085434d29027978dc36867fe9c5bcea9376654b7a8eba1e52dfc2"
EXPECTED_NNUE_SIZE=98511183

mkdir -p "${BUILD_DIR}/bin" "${BUILD_DIR}/dl" "${RESULTS_DIR}"

echo "================================================================================"
echo " STOCKFISH 19 PRO — KHỞI TẠO LÒ LUYỆN KINH NGHIỆM TỐI THƯỢNG (5H30P DOJO)"
echo " Google Drive Input ID: ${PRO_GDRIVE_ID}"
echo "================================================================================"

# 1. Tự động giải nén gói dojo nếu người dùng đẩy file zip lên gốc repo
if [ ! -d "${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/src" ]; then
    for z in "${REPO_ROOT}"/*.zip; do
        if [ -f "$z" ]; then
            echo "[UNPACK] Giải nén $z..."
            unzip -oq "$z" -d "${REPO_ROOT}"
            break
        fi
    done
fi

# 2. Tối ưu hóa Kernel Linux (Transparent Huge Pages & CPU Governor)
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo sh -c 'echo always > /sys/kernel/mm/transparent_hugepage/enabled' 2>/dev/null || true
    sudo sysctl -w vm.overcommit_memory=1 >/dev/null 2>&1 || true
    sudo sysctl -w kernel.sched_autogroup_enabled=0 >/dev/null 2>&1 || true
fi

# 3. Tải file từ Google Drive (1PdgGTXNhHOwZy_39nmc4C0vmlyaF6EJO)
DL_FILE="${BUILD_DIR}/dl/gdrive_input.bin"
if [ ! -s "${DL_FILE}" ]; then
    echo "[GDRIVE] Đang tải tệp từ Google Drive (ID: ${PRO_GDRIVE_ID})..."
    if command -v gdown >/dev/null 2>&1; then
        gdown --fuzzy "https://drive.google.com/file/d/${PRO_GDRIVE_ID}/view?usp=drivesdk" -O "${DL_FILE}" || true
    elif python3 -c "import gdown" >/dev/null 2>&1; then
        python3 -m gdown --fuzzy "https://drive.google.com/file/d/${PRO_GDRIVE_ID}/view?usp=drivesdk" -O "${DL_FILE}" || true
    fi

    if [ ! -s "${DL_FILE}" ] && command -v curl >/dev/null 2>&1; then
        curl -sSfL --retry 3 --max-time 600 \
            "https://drive.usercontent.google.com/download?id=${PRO_GDRIVE_ID}&export=download&confirm=t" \
            -o "${DL_FILE}" || true
    fi
fi

# 4. Trích xuất mạng NNUE (nn-1a298aa575a0.nnue) và experience.bin (nếu có) từ file tải về
NNUE_DEST="${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/src/${EXPECTED_NNUE_NAME}"
EXP_SEED="${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/experience/experience.bin"

python3 - "${DL_FILE}" "${NNUE_DEST}" "${EXP_SEED}" "${REPO_ROOT}" << 'PYEOF'
import hashlib, os, shutil, subprocess, sys, tarfile, zipfile
from pathlib import Path

dl_file, nnue_dest, exp_seed, repo_root = [Path(p) for p in sys.argv[1:5]]
EXPECTED_SHA = "1a298aa575a085434d29027978dc36867fe9c5bcea9376654b7a8eba1e52dfc2"
EXPECTED_SIZE = 98511183

def verify_nnue(p: Path) -> bool:
    if not p.is_file() or p.stat().st_size != EXPECTED_SIZE:
        return False
    return hashlib.sha256(p.read_bytes()).hexdigest() == EXPECTED_SHA

# Check if NNUE already exists in repo_root or system cache
for cand in [
    nnue_dest,
    repo_root / "nn-1a298aa575a0.nnue",
    Path("/usr/local/share/sf_v3_work/Stockfish-19-Pro-Ultimate-V3/nn-1a298aa575a0.nnue"),
]:
    if verify_nnue(cand):
        if cand != nnue_dest:
            shutil.copy2(cand, nnue_dest)
        print(f"[NNUE] Đã có sẵn mạng NNUE hợp lệ tại {nnue_dest}")
        break

if not verify_nnue(nnue_dest) and dl_file.is_file() and dl_file.stat().st_size > 1000000:
    raw = dl_file.read_bytes()
    # Case A: tar.gz archive
    if raw[:2] == b"\x1f\x8b":
        print("[EXTRACT] Phát hiện tệp nén .tar.gz từ Google Drive, đang giải nén...")
        ext_dir = dl_file.parent / "extracted"
        ext_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(dl_file, "r:gz") as tf:
            tf.extractall(ext_dir)
        for p in ext_dir.rglob("nn-1a298aa575a0.nnue"):
            if verify_nnue(p):
                shutil.copy2(p, nnue_dest)
                print("[NNUE] Đã trích xuất nn-1a298aa575a0.nnue từ gói .tar.gz")
                break
        for p in ext_dir.rglob("experience.bin"):
            if p.stat().st_size > exp_seed.stat().st_size:
                shutil.copy2(p, exp_seed)
                print(f"[EXP] Đã cập nhật experience.bin ({p.stat().st_size} bytes) từ gói .tar.gz")
    # Case B: zip archive
    elif raw[:4] == b"PK\x03\x04":
        print("[EXTRACT] Phát hiện tệp nén .zip từ Google Drive, đang giải nén...")
        ext_dir = dl_file.parent / "extracted"
        ext_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dl_file, "r") as zf:
            zf.extractall(ext_dir)
        for p in ext_dir.rglob("nn-1a298aa575a0.nnue"):
            if verify_nnue(p):
                shutil.copy2(p, nnue_dest)
                break
    # Case C: ELF binary with embedded NNUE
    elif raw[:4] == b"\x7fELF" and len(raw) >= EXPECTED_SIZE:
        print("[EXTRACT] Phát hiện ELF Binary từ Google Drive, đang quét trích xuất mạng NNUE nhúng bên trong...")
        nnue_magic = b"\x7a\x3c\x2f\x02"  # Stockfish NNUE version header
        pos = 0
        while True:
            idx = raw.find(nnue_magic, pos)
            if idx == -1 or idx + EXPECTED_SIZE > len(raw):
                break
            chunk = raw[idx:idx + EXPECTED_SIZE]
            if hashlib.sha256(chunk).hexdigest() == EXPECTED_SHA:
                nnue_dest.write_bytes(chunk)
                print(f"[NNUE] Trích xuất thành công 98.5MB NNUE từ offset {idx} của ELF binary!")
                break
            pos = idx + 4

if not verify_nnue(nnue_dest):
    print("[NNUE] Tải mạng chuẩn nn-1a298aa575a0.nnue từ kho chính thức Stockfish...")
    subprocess.run([
        "curl", "-sSfL", "--retry", "3",
        "https://data.stockfishchess.org/nn/nn-1a298aa575a0.nnue",
        "-o", str(nnue_dest)
    ], check=True)
    assert verify_nnue(nnue_dest), "SHA256 mạng NNUE không khớp!"
PYEOF

# 5. Biên dịch Native Linux Stockfish 19 Pro & Sparring Partner
UNAME_M="$(uname -m)"
if [ "${UNAME_M}" = "aarch64" ] || [ "${UNAME_M}" = "arm64" ]; then
    TARGET_ARCH="armv8-dotprod"
else
    TARGET_ARCH="x86-64-avx2"
fi

SRC_DIR="${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/src"
echo "[BUILD] Đang biên dịch Stockfish 19 Pro cho kiến trúc ${TARGET_ARCH} (Cores: $(nproc))..."
make -C "${SRC_DIR}" clean >/dev/null
make -C "${SRC_DIR}" -j"$(nproc)" build ARCH="${TARGET_ARCH}" COMP=gcc

cp -f "${SRC_DIR}/stockfish" "${BUILD_DIR}/bin/stockfish-pro"
cp -f "${SRC_DIR}/stockfish" "${BUILD_DIR}/bin/stockfish-sparring"
cp -f "${NNUE_DEST}" "${BUILD_DIR}/bin/${EXPECTED_NNUE_NAME}"
cp -f "${EXP_SEED}" "${BUILD_DIR}/bin/experience.bin"
chmod +x "${BUILD_DIR}/bin/stockfish-pro" "${BUILD_DIR}/bin/stockfish-sparring"

echo "[VERIFY] Kiểm tra khởi động Stockfish 19 Pro và kho kinh nghiệm khởi điểm:"
"${BUILD_DIR}/bin/stockfish-pro" << EOF
uci
setoption name Experience File value ${BUILD_DIR}/bin/experience.bin
isready
expinfo
quit
EOF
echo "[OK] Hoàn tất chuẩn bị Lò Luyện Kinh Nghiệm 5h30p!"

mkdir -p "$BUILD_DIR/pro_root/nnue"
cp -f "$NNUE_PATH" "$BUILD_DIR/pro_root/nnue/nn-1a298aa575a0.nnue" 2>/dev/null || true
