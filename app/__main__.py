"""Jalankan: python -m app"""
from . import bot, config, db, scheduler


def main():
    db.init()
    if config.THREADS_ACCESS_TOKEN and not db.all_accounts():
        try:
            username = bot.connect_token(config.THREADS_ACCESS_TOKEN)
            print(f"Akun @{username} terhubung dari THREADS_ACCESS_TOKEN")
        except Exception as e:
            print(f"THREADS_ACCESS_TOKEN gagal dipakai: {e}")
    scheduler.start()
    bot.run_forever()


if __name__ == "__main__":
    main()
