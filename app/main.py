import json
import logging
import requests
import socket
from struct import pack
import time
from configparser import ConfigParser
from telegram.ext import Updater, CommandHandler, CallbackContext

config = ConfigParser()
config.read('user.cfg')

telegram = config["TELEGRAM"]
tplink = config["TPLINK"]
miner = config["MINER"]
settings = config["SETTINGS"]

AUTOMATIC_REBOOTS = settings['auto_reboot']
HEARTBEAT_MESSAGE = settings['heartbeat']

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# ======================================================================================================================
#                                             TP-Link interface functions
# ======================================================================================================================
def encrypt(string):
    key = 171
    result = pack(">I", len(string))
    for i in string:
        a = key ^ ord(i)
        key = a
        result += bytes([a])
    return result


def decrypt(string):
    key = 171
    result = ""
    for i in string:
        a = key ^ i
        key = i
        result += chr(a)
    return result


def send_tplink_command(cmd):
    try:
        sock_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_tcp.settimeout(10)
        sock_tcp.connect((tplink['ip'], int(tplink['port'])))
        sock_tcp.send(encrypt(cmd))
        data = sock_tcp.recv(2048)
        sock_tcp.close()

        decrypted = decrypt(data[4:])

        print("Sent:     ", cmd)
        print("Received: ", decrypted)

    except socket.error:
        quit(f"Could not connect to host {tplink['ip']}:{tplink['port']}")


# ======================================================================================================================
#                                               Telegram bot functions
# ======================================================================================================================
def help(update, context):

    logger.info("sending help message")
    message = '/help Display this help message\n' \
              '/status Get miner info\n' \
              '/on Turn TP-Link plug on\n' \
              '/off Turn TP-Link plug off\n' \
              '/reboot Turns the TP-Link plug off then on, with a 30s delay\n' \
              '/disablereboot Disables automatic reboot of the TP-Link\n' \
              '/enablereboot Enables automatic reboots of the TP-Link\n' \
              '/disableheartbeat Disables the heartbeat message for when the miner is running with no issues\n' \
              '/enableheartbeat Enables the heartbeat message for when the miner is running with no issues'

    context.bot.send_message(chat_id=update.effective_chat.id, text=message)


def status(update, context):
    logger.info("querying miner for status")
    try:
        global HEARTBEAT_MESSAGE
        global AUTOMATIC_REBOOTS
        r = requests.get(f'http://{miner["ip"]}', params="json=true")
        j = r.json()
        message = f'Hotspot name: {j["AN"]}\n' \
                  f'Relayed status: {j["MR"]}\n' \
                  f'Height status: {j["BCH"]}/{j["MH"]}\n' \
                  f'Firmware version: {j["FW"]}\n' \
                  f'Last updated: {j["last_updated"]}\n' \
                  f'Reboot enabled: {AUTOMATIC_REBOOTS}\n' \
                  f'Heartbeat enabled: {HEARTBEAT_MESSAGE}'

    except requests.exceptions.HTTPError:
        message = f'Unable to talk to hotspot at {miner["ip"]}, please check URL is accessible'

    context.bot.send_message(chat_id=update.effective_chat.id, text=message)


def reboot(*args):
    # Reboot the TP-Link
    # send_tplink_command('{"system":{"reboot":{"delay":0}}}')
    logger.info("rebooting tplink")
    send_tplink_command('{"system":{"set_relay_state":{"state":0}}}')
    time.sleep(30)
    send_tplink_command('{"system":{"set_relay_state":{"state":1}}}')
    logger.info("tplink rebooted")


def on(*args):
    send_tplink_command('{"system":{"set_relay_state":{"state":1}}}')
    logger.info("tplink turned on")


def off(*args):
    send_tplink_command('{"system":{"set_relay_state":{"state":0}}}')
    logger.info("tplink turned off")


def disable_reboot(*args):
    global AUTOMATIC_RESTARTS
    AUTOMATIC_RESTARTS = False
    logger.info("reboot disabled")


def enable_reboot(*args):
    global AUTOMATIC_RESTARTS
    AUTOMATIC_RESTARTS = True
    logger.info("reboot enabled")


def disable_heartbeat(*args):
    global HEARTBEAT_MESSAGE
    HEARTBEAT_MESSAGE = False
    logger.info("heartbeat disabled")


def enable_heartbeat(*args):
    global HEARTBEAT_MESSAGE
    HEARTBEAT_MESSAGE = True
    logger.info("heartbeat enabled")


# ======================================================================================================================
#                                             Scheduled health checker
# ======================================================================================================================

def health_check(context: CallbackContext):
    logger.info('Running miner health check')
    online_status = True
    relayed_status = False
    restart_needed = False

    try:
        r = requests.get(f'http://{miner["ip"]}', params="json=true")
        j = r.json()
        logger.info(f'Relayed status: {j["MR"]}')
        if j["MR"]:
            context.bot.send_message(chat_id=telegram['chat_id'], text=f'Miner relayed, restart needed')
            relayed_status = True
            restart_needed = True
    except requests.exceptions.HTTPError as e:
        context.bot.send_message(chat_id=telegram['chat_id'], text=f'Error when pinging miner, restart needed: {e}')
        online_status = False
        restart_needed = True

    if restart_needed and AUTOMATIC_RESTARTS:
        context.bot.send_message(chat_id=telegram['chat_id'], text=f'Restarting miner\n'
                                                                   f'Online: {online_status}\n, '
                                                                   f'Relayed: {relayed_status}')
        reboot()

    if HEARTBEAT_MESSAGE and not restart_needed:
        context.bot.send_message(chat_id=telegram['chat_id'], text=f'All is fine: online - True, relayed - False')


# ======================================================================================================================
#                                             Telegram bot configuration
# ======================================================================================================================
def main():
    logger.info("Starting up Bot")

    # timezone = pytz.timezone('Europe/Paris')
    # defaults = Defaults(tzinfo=timezone)

    updater = Updater(token=telegram['token'], use_context=True)

    help_handler = CommandHandler('help', help)
    about_handler = CommandHandler('about', help)
    status_handler = CommandHandler('status', status)
    reboot_handler = CommandHandler('reboot', reboot)
    restart_handler = CommandHandler('restart', reboot)
    on_handler = CommandHandler('on', on)
    off_handler = CommandHandler('off', off)
    disable_reboot_handler = CommandHandler('disablereboot', disable_reboot)
    enable_reboot_handler = CommandHandler('enablereboot', disable_reboot)
    disable_heartbeat_handler = CommandHandler('disableheartbeat', disable_heartbeat)
    enable_heartbeat_handler = CommandHandler('enableheartbeat', enable_heartbeat)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(help_handler)
    dispatcher.add_handler(about_handler)
    dispatcher.add_handler(status_handler)
    dispatcher.add_handler(reboot_handler)
    dispatcher.add_handler(restart_handler)
    dispatcher.add_handler(on_handler)
    dispatcher.add_handler(off_handler)
    dispatcher.add_handler(disable_reboot_handler)
    dispatcher.add_handler(enable_reboot_handler)
    dispatcher.add_handler(disable_heartbeat_handler)
    dispatcher.add_handler(enable_heartbeat_handler)

    # updater.start_polling()

    j = updater.job_queue
    j.run_repeating(health_check, 300)

    updater.start_polling()
    updater.idle()
    logger.info('Bot started.')


if __name__ == '__main__':
    main()
