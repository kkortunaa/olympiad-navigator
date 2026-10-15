"""Start the existing Django app on the Mac's Wi-Fi address and generate a QR."""
import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP = ROOT / 'scuns'


def wifi_address():
    for interface in ('en0', 'en1'):
        result = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface],
                                capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise SystemExit('Не найден Wi-Fi адрес. Подключитесь к Wi-Fi или укажите --host IP.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', help='Wi-Fi IPv4 address; detected automatically on macOS')
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--prepare-only', action='store_true', help='Generate QR without starting server')
    args = parser.parse_args()
    host = args.host or wifi_address()
    address = ipaddress.IPv4Address(host)
    if not address.is_private or address.is_loopback or address.is_unspecified or address.is_link_local:
        parser.error('Нужен частный IPv4 адрес компьютера в Wi-Fi сети.')
    if not 1024 <= args.port <= 65535:
        parser.error('Порт должен быть от 1024 до 65535.')
    if not args.prepare_only:
        with socket.socket() as probe:
            try:
                probe.bind((host, args.port))
            except OSError as error:
                raise SystemExit(f'Не удалось открыть {host}:{args.port}: {error}')

    url = f'http://{host}:{args.port}/'
    swift = shutil.which('swift')
    if not swift:
        raise SystemExit('Для генерации QR нужен Swift из инструментов разработчика macOS.')
    subprocess.run([swift, '-module-cache-path', '/tmp/olympiad-qr-swift-cache',
                    str(HERE / 'make_qr.swift'), url, str(HERE / 'site-qr.png')], check=True)
    (HERE / 'site-url.txt').write_text(url + '\n', encoding='utf-8')
    print(f'\nАдрес для зрителей: {url}\nQR: {HERE / "site-qr.png"}', flush=True)
    if args.prepare_only:
        return

    env = os.environ.copy()
    env['DJANGO_ALLOWED_HOSTS'] = f'{host},127.0.0.1,localhost'
    env['DJANGO_DEBUG'] = '0'
    # Reuse the existing key without printing it; the demo uses the existing database.
    secret_file = APP / '.dev-secret'
    env['DJANGO_SECRET_KEY'] = env.get('DJANGO_SECRET_KEY') or (
        secret_file.read_text().strip() if secret_file.exists() else secrets.token_urlsafe(50))
    env['PYTHONPATH'] = str(HERE) + os.pathsep + env.get('PYTHONPATH', '')
    print('Локальный показ: HTTP, доверенная Wi-Fi сеть. Для остановки нажмите Ctrl+C.\n'
          'Адрес и QR нужно обновить после смены Wi-Fi или IP.\n', flush=True)
    os.chdir(APP)
    os.execve(sys.executable, [sys.executable, str(APP / 'manage.py'), 'runserver',
                              f'{host}:{args.port}', '--settings=wifi_settings',
                              '--insecure', '--noreload'], env)


if __name__ == '__main__':
    main()
