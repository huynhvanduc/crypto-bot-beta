#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/huynhvanduc/crypto-bot-beta.git"
DIR="$HOME/crypto-bot-beta"
DL="$HOME/storage/downloads"

step() { printf '\n\033[1;36m== %s\033[0m\n' "$1"; }
ask() { local v; read -r -p "$1" v </dev/tty; printf '%s' "$v"; }
ask_secret() { local v; read -r -s -p "$1" v </dev/tty; echo >/dev/tty; printf '%s' "$v"; }

step "1/7 Cài gói hệ thống (lần đầu mất 5–15 phút)"
pkg upgrade -y -o Dpkg::Options::=--force-confnew
pkg install -y git gh python util-linux tur-repo
pkg update -y
pkg install -y python-numpy python-pandas || {
    echo "Không có gói dựng sẵn, cài pandas bằng pip (có thể mất 20–40 phút)..."
    export CFLAGS="-Wno-deprecated-declarations -Wno-unreachable-code"
    pip install numpy pandas
}
pip install requests websocket-client
python -c "import numpy, pandas, requests, websocket" || {
    echo "LỖI: thiếu thư viện Python (xem dòng báo lỗi ở trên). Dừng cài đặt."
    exit 1
}

step "2/7 Quyền đọc thư mục Download"
[ -d "$DL" ] || termux-setup-storage
sleep 2

step "3/7 Tải bot"
if [ -d "$DIR/.git" ]; then
    git -C "$DIR" pull --ff-only
else
    git clone "$REPO" "$DIR"
fi
chmod +x "$DIR"/android/*.sh

step "4/7 Đăng nhập GitHub (để bot cập nhật dashboard)"
gh auth status >/dev/null 2>&1 || gh auth login -h github.com -p https -w
gh auth setup-git
LOGIN=$(gh api user -q .login)
UID_GH=$(gh api user -q .id)
git -C "$DIR" config user.name "$LOGIN"
git -C "$DIR" config user.email "$UID_GH+$LOGIN@users.noreply.github.com"

step "5/7 Khóa API Binance testnet"
if [ -f "$DIR/.env" ]; then
    echo "Đã có $DIR/.env — giữ nguyên."
elif [ -f "$DL/bot.env" ]; then
    cp "$DL/bot.env" "$DIR/.env"
    rm -f "$DL/bot.env"
    echo "Đã lấy khóa từ Download/bot.env (và xóa file đó khỏi Download)."
else
    KEY=$(ask_secret "BINANCE_API_KEY: ")
    SECRET=$(ask_secret "BINANCE_API_SECRET: ")
    TOPIC=$(ask "NTFY_TOPIC: ")
    TG=$(ask_secret "TELEGRAM_BOT_TOKEN (Enter để bỏ qua): ")
    printf 'BINANCE_API_KEY=%s\nBINANCE_API_SECRET=%s\nBINANCE_BASE_URL=https://testnet.binance.vision\nNTFY_TOPIC=%s\nTELEGRAM_BOT_TOKEN=%s\n' \
        "$KEY" "$SECRET" "$TOPIC" "$TG" > "$DIR/.env"
fi
chmod 600 "$DIR/.env"

step "6/7 Trạng thái bot (vốn, lệnh đang mở, lệnh khớp)"
mkdir -p "$DIR/live"
for f in state.json fills.json telegram.json manual.json; do
    if [ -f "$DIR/live/$f" ]; then
        echo "Đã có live/$f — giữ nguyên."
    elif [ -f "$DL/$f" ]; then
        mv "$DL/$f" "$DIR/live/$f"
        echo "Đã chuyển Download/$f vào bot."
    fi
done
if [ ! -f "$DIR/live/state.json" ]; then
    GIST=$(ask "Mã chuyển trạng thái (gist), Enter để bỏ qua: ")
    if [ -n "$GIST" ]; then
        for f in state.json fills.json; do
            gh gist view "$GIST" -f "$f" --raw > "$DIR/live/$f"
            python -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" "$DIR/live/$f"
            echo "Đã tải $f từ gist."
        done
    fi
fi
if [ ! -f "$DIR/live/state.json" ]; then
    echo "KHÔNG thấy state.json (chép từ máy tính D:\\LearnCode\\bot\\live\\ vào thư mục Download)."
    [ "$(ask 'Gõ MOI để bắt đầu bot từ đầu, phím khác để dừng: ')" = "MOI" ] || exit 1
fi

step "7/7 Tự chạy khi điện thoại khởi động (cần app Termux:Boot)"
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/crypto-bot.sh" <<EOF
#!/usr/bin/env bash
termux-wake-lock
bash "$DIR/android/bot.sh" start
EOF
chmod +x "$HOME/.termux/boot/crypto-bot.sh"

bash "$DIR/android/bot.sh" start

cat <<EOF

Xong. Lệnh điều khiển (gõ trong Termux):
  bash $DIR/android/bot.sh status     # đang chạy chưa, log gần nhất
  bash $DIR/android/bot.sh stop       # dừng bot
  bash $DIR/android/bot.sh ban-het    # bán hết + tạm dừng mua mới
  bash $DIR/android/bot.sh tam-dung   # tạm dừng mua mới
  bash $DIR/android/bot.sh tiep-tuc   # bật lại

Để bot không bị Android tắt:
  - Cài app Termux:Boot (cùng nguồn với Termux, F-Droid) và mở nó 1 lần.
  - Cài đặt > Ứng dụng > Termux > Pin: "Không hạn chế" (tắt tối ưu pin).
  - Cắm sạc và giữ wifi.
EOF
