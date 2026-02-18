from telegram import Bot
import asyncio

bot = Bot("8441441183:AAFUk4MV8hplVyKV7I5K19K_FW2cbxDdVt0")


async def main():
    me = await bot.get_me()
    print(me)

asyncio.run(main())

