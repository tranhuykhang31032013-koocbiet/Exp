#!/usr/bin/env bash
set -e

PRO_GDRIVE_ID="${1:-${PRO_GDRIVE_ID:-1PdgGTXNhHOwZy_39nmc4C0vmlyaF6EJO}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build"
RESULTS_DIR="${REPO_ROOT}/results"
EXPECTED_NNUE_NAME="nn-1a298aa575a0.nnue"
EXPECTED_NNUE_SIZE=98511183

mkdir -p "${BUILD_DIR}/bin" "${BUILD_DIR}/dl" "${RESULTS_DIR}"
chmod +x "${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/scripts/"*.sh 2>/dev/null || true

echo "================================================================================"
echo " STOCKFISH 19 PRO — KHOI TAO LO LUYEN DA TANG (5H30P OMNISCIENT DOJO)"
echo " Google Drive Input ID: ${PRO_GDRIVE_ID}"
echo "================================================================================"

DL_FILE="${BUILD_DIR}/dl/gdrive_input.bin"
if [ ! -s "${DL_FILE}" ]; then
    echo "[GDRIVE] Dang tai tep tu Google Drive (ID: ${PRO_GDRIVE_ID})..."
    curl -sSfL --retry 3 --max-time 600 \
        "https://drive.usercontent.google.com/download?id=${PRO_GDRIVE_ID}&export=download&confirm=t" \
        -o "${DL_FILE}" || true
    if [ ! -s "${DL_FILE}" ] && command -v gdown >/dev/null 2>&1; then
        gdown "${PRO_GDRIVE_ID}" -O "${DL_FILE}" || true
    fi
fi

NNUE_DEST="${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/src/${EXPECTED_NNUE_NAME}"
EXP_SEED="${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/experience/experience.bin"

python3 - "${DL_FILE}" "${NNUE_DEST}" "${EXP_SEED}" << 'PYEOF'
import hashlib, shutil, subprocess, sys, tarfile, zipfile
from pathlib import Path

dl_file, nnue_dest, exp_seed = [Path(p) for p in sys.argv[1:4]]
EXPECTED_SHA = "1a298aa575a085434d29027978dc36867fe9c5bcea9376654b7a8eba1e52dfc2"
EXPECTED_SIZE = 98511183
NNUE_MAGIC_8 = bytes.fromhex("fa8a446a05225ba8")
NNUE_SIG = b"Network trained with the https://github.com/official-stockfish/nnue-pytorch trainer."

def is_valid(p: Path) -> bool:
    return p.is_file() and p.stat().st_size == EXPECTED_SIZE

if not is_valid(nnue_dest) and dl_file.is_file() and dl_file.stat().st_size > 1000000:
    raw = dl_file.read_bytes()
    print(f"[EXTRACT] Da tai {len(raw):,} bytes tu Google Drive, dang trich xuat NNUE...")
    if len(raw) == EXPECTED_SIZE:
        nnue_dest.write_bytes(raw)
    elif raw[:2] == b"\x1f\x8b":
        ext_dir = dl_file.parent / "extracted"
        ext_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(dl_file, "r:gz") as tf:
            tf.extractall(ext_dir)
        for p in ext_dir.rglob("*.nnue"):
            if p.stat().st_size >= 50000000:
                shutil.copy2(p, nnue_dest)
                break
        for p in ext_dir.rglob("experience.bin"):
            if p.stat().st_size > exp_seed.stat().st_size:
                shutil.copy2(p, exp_seed)
    elif raw[:4] == b"PK\x03\x04":
        ext_dir = dl_file.parent / "extracted"
        ext_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dl_file, "r") as zf:
            zf.extractall(ext_dir)
        for p in ext_dir.rglob("*.nnue"):
            if p.stat().st_size >= 50000000:
                shutil.copy2(p, nnue_dest)
                break
    else:
        idx = raw.find(NNUE_MAGIC_8)
        if idx != -1 and idx + EXPECTED_SIZE <= len(raw):
            nnue_dest.write_bytes(raw[idx : idx + EXPECTED_SIZE])
            print(f"[NNUE] Trich xuat thanh cong 98.5MB NNUE (magic fa8a446a) tai offset {idx}!")
        else:
            sig_idx = raw.find(NNUE_SIG)
            if sig_idx >= 12 and sig_idx - 12 + EXPECTED_SIZE <= len(raw):
                start = sig_idx - 12
                nnue_dest.write_bytes(raw[start : start + EXPECTED_SIZE])
                print(f"[NNUE] Trich xuat thanh cong 98.5MB NNUE (signature) tai offset {start}!")

if not is_valid(nnue_dest):
    for url in [
        "https://tests.stockfishchess.org/api/nn/nn-1a298aa575a0.nnue",
        "https://github.com/official-stockfish/networks/raw/master/nn-1a298aa575a0.nnue",
    ]:
        print(f"[NNUE] Fallback tai tu {url} ...")
        subprocess.run(["curl", "-sSfL", "--retry", "3", url, "-o", str(nnue_dest)], check=False)
        if is_valid(nnue_dest):
            break

if not is_valid(nnue_dest):
    print("LOI: Khong tim thay mang NNUE hop le!")
    sys.exit(1)
print(f"[OK] Mang NNUE san sang: {nnue_dest} ({nnue_dest.stat().st_size:,} bytes)")
PYEOF

rm -rf "${BUILD_DIR}/pro_root"
cp -r "${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3" "${BUILD_DIR}/pro_root"
mkdir -p "${BUILD_DIR}/pro_root/nnue" "${BUILD_DIR}/pro_root/experience"
cp -f "${NNUE_DEST}" "${BUILD_DIR}/pro_root/nnue/${EXPECTED_NNUE_NAME}"
cp -f "${NNUE_DEST}" "${BUILD_DIR}/pro_root/src/${EXPECTED_NNUE_NAME}"
cp -f "${EXP_SEED}" "${BUILD_DIR}/seed_experience.bin"
cp -f "${EXP_SEED}" "${BUILD_DIR}/bin/experience.bin"

UNAME_M="$(uname -m)"
if [ "${UNAME_M}" = "aarch64" ] || [ "${UNAME_M}" = "arm64" ]; then
    TARGET_ARCH="armv8-dotprod"
else
    TARGET_ARCH="x86-64-avx2"
fi

SRC_DIR="${REPO_ROOT}/engines/Stockfish-19-Pro-Ultimate-V3/src"
echo "[BUILD] Dang bien dich Stockfish 19 Pro (${TARGET_ARCH}, $(nproc) cores)..."
make -C "${SRC_DIR}" clean >/dev/null || true
make -C "${SRC_DIR}" -j"$(nproc)" build ARCH="${TARGET_ARCH}" COMP=gcc || make -C "${SRC_DIR}" -j"$(nproc)" build ARCH="${TARGET_ARCH}" COMP=clang

cp -f "${SRC_DIR}/stockfish" "${BUILD_DIR}/bin/stockfish-pro"
cp -f "${SRC_DIR}/stockfish" "${BUILD_DIR}/bin/stockfish-sparring"
cp -f "${NNUE_DEST}" "${BUILD_DIR}/bin/${EXPECTED_NNUE_NAME}"
chmod +x "${BUILD_DIR}/bin/stockfish-pro" "${BUILD_DIR}/bin/stockfish-sparring"

"${BUILD_DIR}/bin/stockfish-pro" << 'UCI_EOF'
uci
isready
expinfo
quit
UCI_EOF
echo "[OK] Hoan tat chuan bi Lo Luyen Kinh Nghiem 5h30p!"
