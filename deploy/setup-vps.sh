#!/bin/bash
# Скрипт установки на чистый Ubuntu/Debian VPS
# Запускать от root: bash deploy/setup-vps.sh

set -e

echo "=== Algo Trading Bot — VPS Setup ==="

# 1. Системные пакеты
apt-get update
apt-get install -y python3.11 python3.11-venv python3-pip git

# 2. Юзер для бота
useradd -r -m -d /opt/algo_trading -s /bin/bash trader 2>/dev/null || true

# 3. Скопировать проект
PROJECT_DIR="/opt/algo_trading"
mkdir -p $PROJECT_DIR
cp -r . $PROJECT_DIR/
chown -R trader:trader $PROJECT_DIR

# 4. Виртуальное окружение
su - trader -c "
  cd $PROJECT_DIR
  python3.11 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
"

# 5. Настроить конфиг
if [ ! -f "$PROJECT_DIR/config/settings.yaml" ]; then
  cp $PROJECT_DIR/config/settings.example.yaml $PROJECT_DIR/config/settings.yaml
  echo ">>> Отредактируй конфиг: nano $PROJECT_DIR/config/settings.yaml"
fi

# 6. Создать .env для ключей
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env
  chmod 600 $PROJECT_DIR/.env
  echo ">>> Добавь API ключи: nano $PROJECT_DIR/.env"
fi

# 7. Создать директории
mkdir -p $PROJECT_DIR/{data,logs}
chown -R trader:trader $PROJECT_DIR

# 8. Установить systemd сервис
cp $PROJECT_DIR/deploy/algo-trading.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable algo-trading

echo ""
echo "=== Готово! ==="
echo ""
echo "Следующие шаги:"
echo "  1. nano $PROJECT_DIR/.env              # API ключи"
echo "  2. nano $PROJECT_DIR/config/settings.yaml  # Настройки"
echo "  3. systemctl start algo-trading            # Запустить бота"
echo "  4. journalctl -u algo-trading -f           # Смотреть логи"
echo ""
