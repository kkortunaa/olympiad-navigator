"""Cross-platform local setup and launch. Run with Python 3.10 or newer."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Установка и запуск Олимпиадного навигатора')
    parser.add_argument('--setup-only', action='store_true', help='Установить зависимости и подготовить БД без запуска сервера')
    parser.add_argument('--install', action='store_true', help='Повторно установить зависимости после обновления кода')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Порт должен быть от 1024 до 65535.')
    environment = ROOT / '.venv-app'
    python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    marker = environment / '.navigator-requirements'
    requirements = (ROOT / 'requirements.txt').read_bytes()
    if not python.exists():
        if sys.version_info < (3, 10):
            parser.error('Для первой установки нужен Python 3.10 или новее. Рекомендуется Python 3.12.')
        print('Создаём виртуальное окружение…', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    version = subprocess.check_output([str(python), '-c', 'import sys; print(sys.version_info >= (3, 10))'], text=True).strip()
    if version != 'True':
        parser.error('В .venv-app находится старый Python. Переименуйте папку .venv-app и повторите запуск через Python 3.10+.')
    if args.install or not marker.exists() or marker.read_bytes() != requirements:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
        marker.write_bytes(requirements)
    manage = [str(python), str(ROOT / 'scuns' / 'manage.py')]
    for command in ('migrate', 'bootstrap_catalog', 'check'):
        subprocess.run(manage + [command], cwd=ROOT / 'scuns', check=True)
    if not args.setup_only:
        print(f'Откройте http://127.0.0.1:{args.port}/ · Остановка: Ctrl+C', flush=True)
        subprocess.run(manage + ['runserver', f'127.0.0.1:{args.port}'], cwd=ROOT / 'scuns', check=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except subprocess.CalledProcessError as error:
        print('Не удалось завершить запуск. Причина указана выше.', file=sys.stderr)
        sys.exit(error.returncode)
