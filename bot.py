from telegram.error import Unauthorized, BadRequest
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, run_async
from telegram import ParseMode
import logging
from html import escape
from decouple import config
from emoji import emojize

from util.database import DatabaseHandler
from util.feedhandler import FeedHandler
from util.processing import BatchProcess

# Configuration
LOG = config('LOG')
CHAT_ID = config('CHAT_ID')
TOKEN = config('TOKEN')
updater = Updater(TOKEN, use_context=True)
dp = updater.dispatcher
job_queue = updater.job_queue
db = DatabaseHandler(0)

logging.basicConfig(level=LOG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)
# logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
# logging.getLogger('OiOlaBot').setLevel(logging.WARNING)

help_text = 'Welcomes everyone that enters a group chat that this bot is a ' \
            'part of. By default, only the person who invited the bot into ' \
            'the group is able to change settings.\nCommands:\n\n' \
            '/welcome - Set welcome message\n' \
            '/goodbye - Set goodbye message\n' \
            '/disableWelcome - Disable the goodbye message\n' \
            '/disableGoodbye - Disable the goodbye message\n' \
            '/lock - Only the person who invited the bot can change messages\n' \
            '/unlock - Everyone can change messages\n' \
            '/quiet - Disable "Sorry, only the person who..." ' \
            '& help messages\n' \
            '/unquiet - Enable "Sorry, only the person who..." ' \
            '& help messages\n\n' \
            '/msg <msg> - To send message\n' \
            'You can use _$username_ and _$title_ as placeholders when setting' \
            ' messages. [HTML formatting]' \
            '(https://core.telegram.org/bots/api#formatting-options) ' \
            'is also supported.\n\n' \
            "Controls\n " \
            "/start - Activates the bot. If you have subscribed to RSS feeds, you will receive news from now on\n " \
            "/stop - Deactivates the bot. You won't receive any messages from the bot until you activate the bot again \
            using the start comand\n"

help_text_feed = "RSS Management\n" \
                 "/addurl <url> - Adds a util subscription to your list. or\n" \
                 "/addurl @chanel <url> - Add url in Your chanel to receve feed. or\n" \
                 "/addurl @group <url> - Add url in Your group to receve feed.\n" \
                 "/listurl - Shows all your subscriptions as a list.\n" \
                 "/remove <url> - Removes an exisiting subscription from your list.\n" \
                 "/remove @chanel <url> - Removes url in Your chanel.\n" \
                 "/remove @group <url> - Removes url in Your group.\n" \
                 "Other\n" \
                 "/help - Shows the help menu  :)"


@run_async
def send_async(context, chat_id, text, **kwargs):
    context.bot.sendMessage(chat_id, text, **kwargs)


def _check(update, _, override_lock=None):
    """
    Perform some hecks on the update. If checks were successful, returns True,
    else sends an error message to the chat and returns False.
    """
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id

    if chat_id > 0:
        text = 'Please add me to a group first!'
        update.message.reply_text(text=text)
        return False

    locked = override_lock if override_lock is not None \
        else bool(db.get_value_name_key('group:' + str(chat_id), 'chat_lock'))

    if locked and int(db.get_value_name_key('group:' + str(chat_id), 'chat_adm')) != user_id:
        if not bool(db.get_value_name_key('group:' + str(chat_id), 'chat_quiet')):
            text = 'Sorry, only the person who invited me can do that.'
            update.message.reply_text(text=text)
        return False

    return True


# Welcome a user to the chat
def _welcome(update, _, member=None):
    """ Welcomes a user to the chat """
    chat_id = update.message.chat.id
    chat_title = update.message.chat.title
    first_name = member.first_name
    logger.info(f'{escape(first_name)} joined to chat {chat_id} ({escape(chat_title)})')

    # Pull the custom message for this chat from the database
    text_group = db.get_value_name_key('group:' + str(chat_id), 'chat_welcome')
    if not text_group:
        return

    # Use default message if there's no custom one set
    welcome_text = f'Hello $username! Welcome to $title {emojize(":grinning_face:")}'
    if text_group:
        text = welcome_text + '\n' + text_group

    # Replace placeholders and send message
    else:
        text = welcome_text

    # Replace placeholders and send message
    welcome_text = text.replace('$username', first_name).replace('$title', chat_title)
    update.message.reply_text(text=welcome_text, parse_mode=ParseMode.HTML)


# Introduce the context to a chat its been added to
def _introduce(update, context):
    """
    Introduces the bot to a chat its been added to and saves the user id of the
    user who invited us.
    """
    me = context.bot
    if me.username == 'LiturgiaDiaria_bot':
        _set_daily_liturgy(update)
        return

    chat_title = update.message.chat.title
    chat_id = update.message.chat.id
    first_name = update.effective_user.first_name
    chat_name = ''.join('@' if update.effective_chat.username or update.effective_user.username
                        else update.message.from_user.first_name)
    user_id = update.message.from_user.id

    logger.info(f'Invited by {user_id} to chat {chat_id} ({escape(chat_title)})')

    db.update_group(chat_id=chat_id, chat_name=chat_name, chat_title=chat_title, user_id=user_id)

    text = f'Hello {escape(first_name)}! I will now greet anyone who joins this chat ({chat_title}) with a' \
           f' nice message {emojize(":grinning_face:")} \n\ncheck the /help command for more info!'
    update.message.reply_text(text=text, parse_mode=ParseMode.HTML)


def _set_daily_liturgy(update):
    chat_id = update.message.chat.id
    chat_name = '@' + update.message.chat.username or '@' + update.message.from_user.username \
                or update.message.from_user.first_name
    chat_title = update.message.chat.title
    user_id = update.message.from_user.id
    url = 'http://feeds.feedburner.com/evangelhoddia/dia'
    text = 'You will receive the daily liturgy every day.\nFor more commands click /help'

    db.set_url_to_chat(chat_id=chat_id, chat_name=chat_name, url=url, user_id=user_id)
    update.reply_text(text=text, quote=False)

    logger.info(f'Invited by {user_id} to chat {chat_id} ({escape(chat_title)})')


help_text = help_text + help_text_feed


# Print help text
def start(update, context):
    """ Prints help text """
    me = context.bot
    if me.username == 'LiturgiaDiaria_bot':
        _set_daily_liturgy(update)
        return

    chat_id = update.message.chat.id
    from_user = update.message.from_user.id

    if not bool(db.get_value_name_key('group:' + str(chat_id), 'chat_quiet')) \
            or str(db.get_value_name_key('group:' + str(chat_id), 'chat_adm')) == str(from_user):
        update.message.reply_text(text=help_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


def new_chat_members(update, context):
    me = context.bot
    for member in update.message.new_chat_members:
        if member.first_name == me.first_name:
            return _introduce(update, context)
        else:
            return _welcome(update, context, member)


def left_chat_member(update, context):
    me = context.bot
    member = update.message.left_chat_member
    if member.first_name == me.first_name:
        return
    else:
        return goodbye(update, context)


# Welcome a user to the chat
def goodbye(update, _):
    """ Sends goodbye message when a user left the chat """
    chat_id = update.message.chat.id
    chat_title = update.message.chat.title
    first_name = update.message.left_chat_member.first_name

    logger.info(f'{escape(first_name)} left chat {chat_id} ({escape(chat_title)})')

    # Pull the custom message for this chat from the database
    text = db.get_value_name_key('group:' + str(chat_id), 'chat_goodbye')

    # Goodbye was disabled
    if text == 'False':
        return

    # Use default message if there's no custom one set
    if text is None:
        text = 'Goodbye, $username!'

    # Replace placeholders and send message
    text = text.replace('$username', first_name).replace('$title', chat_title)
    update.message.reply_text(text=text, parse_mode=ParseMode.HTML)


# Set custom message
def set_welcome(update, context):
    """ Sets custom welcome message """
    args = context.args
    chat_id = update.message.chat.id

    # _check admin privilege and group context
    if not _check(update, context):
        return

    # Split message into words and remove mentions of the bot
    set_text = r' '.join(args)

    # Only continue if there's a message
    if not set_text:
        text = 'You need to send a message, too! For example:\n' \
               '<code>/welcome The objective of this group is to...</code>'
        update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
        return

    # Put message into database
    db.set_name_key('group:' + str(chat_id), {'chat_welcome': set_text})
    update.message.reply_text(text='Got it!', parse_mode=ParseMode.HTML)


# Set custom message
def set_goodbye(update, context):
    """ Enables and sets custom goodbye message """
    args = context.args
    chat_id = update.message.chat_id

    # _check admin privilege and group context
    if not _check(update, context):
        return

    # Split message into words and remove mentions of the bot
    set_text = ' '.join(args)

    # Only continue if there's a message
    if not set_text:
        text = 'You need to send a message, too! For example:\n' \
               '<code>/goodbye Goodbye, $username!</code>'
        update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
        return

    # Put message into database
    db.set_name_key('group:' + str(chat_id), {'chat_goodbye': set_text})
    update.message.reply_text(text='Got it!')


def disable_welcome(update, context):
    """ Disables the goodbye message """
    command_control(update, context, 'disable_welcome')


def disable_goodbye(update, context):
    """ Disables the goodbye message """
    command_control(update, context, 'disable_goodbye')


def lock(update, context):
    """ Locks the chat, so only the invitee can change settings """
    command_control(update, context, 'lock')


def unlock(update, context):
    """ Unlocks the chat, so everyone can change settings """
    command_control(update, context, 'unlock')


def quiet(update, context):
    """ Quiets the chat, so no error messages will be sent """
    command_control(update, context, 'quiet')


def unquiet(update, context):
    """ Unquiets the chat """
    command_control(update, context, 'unquiet')


def command_control(update, context, command):
    """ Disables the goodbye message """
    chat_id = update.message.chat_id

    # _check admin privilege and group context
    if _check(update, context):
        if command == 'disable_welcome':
            commit = db.set_name_key('group:' + str(chat_id), {'chat_welcome': 'False'})
        elif command == 'disable_goodbye':
            commit = db.set_name_key('group:' + str(chat_id), {'chat_goodbye': 'False'})
        elif command == 'lock':
            commit = db.set_name_key('group:' + str(chat_id), {'chat_lock': 'True'})
        elif command == 'unlock':
            commit = db.set_name_key('group:' + str(chat_id), {'chat_lock': 'False'})
        elif command == 'quiet':
            commit = db.set_name_key('group:' + str(chat_id), {'chat_quiet': 'True'})
        elif command == 'unquiet':
            commit = db.set_name_key('group:' + str(chat_id), {'chat_quiet': 'False'})
        else:
            commit = False
        if commit:
            update.message.reply_text(text='Got it!')


def new_chat_title(update, context):
    pass
    # chat_title = update.message.chat.title
    # chat_name = update.message.chat.username
    # chat_id = update.message.chat.id
    #
    # keys = db.find_keys('*group:' + str(chat_id) + '*')
    # for key in keys:
    #     db.redis.hmset(key, {str(chat_id) + '_name': chat_name,
    #                          str(chat_id) + '_title': str(chat_title)})
    #
    # keys = db.find_keys('*user_id:' + str(chat_id) + '*')
    # for key in keys:
    #     chat_name = db.redis.hkeys(key)
    #     db.redis.hset(key, chat_title, str(chat_id))
    #     for name in chat_name:
    #         db.redis.hdel(key, name)


def error(update, context, **kwargs):
    """ Error handling """
    print('error', update)

    # try:
    # print("####################################################################")
    # chat_id = update.message.chat.id
    # list_group = db.find_keys('group:*' + str(chat_id))
    # for key in list_group:
    #     for k in db.redis.hvals(key):
    #         if int(k) == int(chat_id):
    #             db.redis.delete(key)
    #             return
    #
    # logger.info('Removed chat_id %s from chat list' % chat_id)
    #
    # logger.error("An error (%s) occurred: %s" % (type(error), context.error.message))

    # except ValueError as e:
    #     logger.error("An error (%s) occurred: %s" % (type(e), e))


def msg(update, context):
    args = context.args
    chat_id = update.message.chat_id
    text = ''
    group_name = None
    for arg in args:
        if str(arg)[:1] == '@':
            group_name = str(arg)
        else:
            text = str(text) + ' ' + str(arg)

    if group_name:
        group_id = get_id(update, context)['user_id']
        if group_id and text:
            send_async(context, chat_id=group_id, text=text)
            return
        else:
            text = 'Group ' + group_name + ' not exist'
            send_async(context, chat_id=chat_id, text=text)
            return

    # groups = db.get_group_id_from_user_id(chat_id=chat_id)
    # for group in groups:
    #     if group and text:
    #         send_async(context, chat_id=group, text=text)


def get_chat_by_username(update, context, user_name=None, chat_id=None):
    get_chat = None
    try:
        if user_name:
            user_name = user_name if user_name[0] == '@' else '@' + str(user_name)
        chat_id = update.effective_chat.id if user_name == '@this' else user_name
        get_chat = context.bot.get_chat(chat_id=chat_id)
    except BadRequest as e:
        if user_name:
            update.message.reply_text(f'I cant resolved username {user_name}')
        print(e)

    user = {}
    if get_chat:
        user.update({'id': str(get_chat.id) or None})
        user.update({'title': get_chat.title}) if get_chat.title \
            else user.update({'first_name': get_chat.first_name})
        user.update({'description': get_chat.description}) if get_chat.description \
            else user.update({'last_name': get_chat.last_name})
        user.update({'username': '@' + get_chat.username if get_chat.username else None})

    return user if get_chat else None


def get_user_info(update, context):
    user_id = update.message.from_user.id
    args = context.args
    command = update.message.text[1:update.message.entities[0].length] or None

    if args:
        user_input = args[0]
        get_chat = get_chat_by_username(update, context, user_name=user_input) if user_input else None

    else:
        get_chat = get_chat_by_username(update, context, chat_id=user_id)

    if get_chat:
        text = '\n'.join(f'{k}: {v}' for k, v in get_chat.items())

        if text and command == 'me':
            update.message.reply_text(text=text, parse_mode=ParseMode.HTML)


def get_id(update, context):
    args = context.args[0]
    from_user = update.message.from_user

    if str(args[0])[:1] == '@':
        id_user = args

    elif not str(args[0]).find('/') < 0:
        id_user = '@' + str(args).split('/')[-1]
    else:
        id_user = '@' + str(args)
    try:
        get_id_user = context.bot.get_chat(chat_id=id_user)
    except Unauthorized as _:
        error(update, context)
        return None

    if get_id_user:
        return {'user_id': get_id_user['id'], 'user_name': "@" + str(get_id_user['username'])}

    else:
        message = "Sorry, " + from_user.first_name + \
                  "! I already have that group name " + id_user + " with stored in your subscriptions."
        update.message.reply_text(message)
        return None


# def get_id_db(update, context):
#     """
#     Removes an rss subscription from user
#     """
#     args = context.args
#     chat_id = update.message.chat_id
#     # _check admin privilege and group context
#     if chat_id < 0:
#         if not _check(update, context):
#             return
#
#     message = "To remove a subscriptions from your list please use " \
#               "/remove <entryname>. To see all your subscriptions along or " \
#               "/remove @username <entryname>. To see all your subscriptions along " \
#               "with their entry names use /listurl !"
#
#     if len(args) > 2:
#         update.message.reply_text(message)
#         return
#
#     url = args[0] if len(args) == 1 else args[1]
#     user_name = args[0] if len(args) == 2 else update.message.chat.first_name
#     group_id_db = db.get_user_id(chat_id, url, user_name)
#     return {'key': group_id_db['key'], 'user_id_db': group_id_db['user_id'], 'user_name_db': user_name, 'url': url,
#             'message': message} if group_id_db else None


# def get_user(update, context):
#     user = get_id_db(update, context)
#     if user:
#         text = 'user_id: ' + str(user['user_id_db']) + \
#                '\n user_name: ' + str(user['user_name_db'])
#         update.message.reply_text(text=text, parse_mode=ParseMode.HTML)


def feed_url(update, url, **chat_info):
    arg_url = FeedHandler.format_url_string(string=url)

    # _check if argument matches url format
    if not FeedHandler.is_parsable(url=arg_url):
        message = "Sorry! It seems like '" + \
                  str(arg_url) + "' doesn't provide an RSS news feed.. Have you tried another URL from that provider?"
        update.message.reply_text(text=message)
        return
    chat_id = chat_info['chat_id']
    chat_name = chat_info.get('chat_name')
    user_id = update.message.from_user.id

    result = db.set_url_to_chat(
        chat_id=str(chat_id), chat_name=str(chat_name), url=url, user_id=str(user_id))

    if result:
        text = "I successfully added " + arg_url + " to your subscriptions!"
    else:
        text = "Sorry, " + update.message.from_user.first_name + \
               "! I already have that url with stored in your subscriptions."
    update.message.reply_text(text)


def add_url(update, context):
    """
    Adds a rss subscription to user
    """
    args = context.args
    chat_id = update.message.chat_id

    # _check admin privilege and group context
    if chat_id < 0:
        if not _check(update, context):
            return

    text = "Sorry! I could not add the entry! " \
           "Please use the the command passing the following arguments:\n\n " \
           "<code>/addurl url</code> or \n <code>/addurl username url</code> \n\n Here is a short example: \n\n " \
           "/addurl http://www.feedforall.com/sample.xml \n\n" \
           "/addurl @username http://www.feedforall.com/sample.xml "

    if len(args) > 2 or not args:
        update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
        return

    elif len(args) == 2:
        chat_name = args[0]
        url = args[1]
        chat_info = get_chat_by_username(update, context, chat_name)
        text = "I don't have access to chat " + chat_name + '\n' + text
        if chat_info is None:
            update.reply_text(text=text, quote=False)
        else:
            chat_info = {'chat_id': chat_info['id'], 'chat_name': chat_info['username']}
            feed_url(update, url, **chat_info)

    else:
        url = args[0]
        user_name = '@' + update.message.chat.username if update.message.chat.username else None
        first_name = update.message.from_user.first_name if update.message.from_user.first_name else None
        chat_title = update.message.chat.title if update.message.chat.title else None

        chat_name = user_name or chat_title or first_name
        user_id = update.message.from_user.id
        chat_info = {'chat_id': chat_id, 'chat_name': chat_name, 'user_id': user_id}

        feed_url(update, url, **chat_info)


def list_url(update, context):
    """
    Displays a list of all user subscriptions
    """
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id

    # _check admin privilege and group context
    if chat_id < 0:
        if not _check(update, context):
            return

    message = "Here is a list of all subscriptions I stored for you!"
    update.message.reply_text(message)

    urls = db.get_chat_urls(user_id=user_id)
    for url in urls:
        url = (str(url['chat_name']) + ' ' if url['chat_name'] and int(url['chat_id']) < 0 else '') + url['url']
        text = '<code>/removeurl ' + url + '</code>'
        # update.message.reply_text(message)
        context.bot.sendMessage(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)


def all_url(update, context):
    """
    Displays a list of all user subscriptions
    """
    chat_id = update.message.chat_id

    # _check admin privilege and group context
    if chat_id < 0:
        if not _check(update, context):
            return

    message = "Here is a list of all subscriptions I stored for you!"
    update.message.reply_text(message)

    urls = db.get_urls_activated()
    for url in urls:
        last_update = db.get_update_url(url)
        text = 'last_update: ' + last_update['last_update'] + '\n\n' \
               + 'last_url: <code>' + last_update['last_url'] + '</code>\n\n' \
               + 'url: <code>' + last_update['url'] + '</code>'

        context.bot.sendMessage(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)


def remove_url(update, context):
    """
    Removes an rss subscription from user
    """
    args = context.args

    text = "Sorry! I could not remove the entry! " \
           "Please use the the command passing the following arguments:\n\n " \
           "<code>/removeurl url</code> or \n <code>/removeurl username url</code> \n\n " \
           "Here is a short example: \n\n " \
           "/removeurl http://www.feedforall.com/sample.xml \n\n" \
           "/removeurl @username http://www.feedforall.com/sample.xml "

    if len(args) > 2 or not args:
        update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
        return

    user_id = update.message.from_user.id
    chat_name = args[0] if len(args) == 2 else None
    chat_id = db.get_chat_id_for_chat_name(user_id, chat_name) if chat_name else update.message.chat.id
    logger.error(f'remove_url {str(chat_id)}')
    url = args[1] if len(args) == 2 else args[0]

    if chat_id is None:
        text = "Don't exist chat " + chat_name + '\n' + text
        update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
    else:
        exist_url = db.exist_url_to_chat(user_id, chat_id, url)
        if not exist_url:
            chat_name = chat_name or update.message.from_user.first_name
            text = "Don't exist " + url + " for chat " + chat_name + '\n' + text
            update.message.reply_text(text=text, parse_mode=ParseMode.HTML)
            result = None
        else:
            result = True if db.del_url_for_chat(chat_id, url) else None

        if result:
            message = "I removed " + url + " from your subscriptions!"
        else:
            message = "I can not find an entry with label " + \
                      url + " in your subscriptions! Please check your subscriptions using " \
                            "/listurl and use the delete command again!"
        update.message.reply_text(text=message)

    names_url = db.find_names(url)
    if names_url == 1:
        db.del_names(names_url)


def get_key(update, context):
    args = context.args
    if len(args) == 1:
        keys = db.find_names(args[0])
        for k in keys:
            text = '<code>/removekey ' + str(k) + '</code>'
            update.message.reply_text(text=str(text), parse_mode=ParseMode.HTML)


def remove_key(update, context):
    args = context.args
    text = 'I removed '
    if len(args) == 1:
        key = args[0]
        if db.redis.delete(args[0]) == 1:
            update.message.reply_text(text=str(text + key), parse_mode=ParseMode.HTML)


def stop(update, context):
    """
    Stops the bot from working
    """
    chat_id = update.message.chat_id

    # _check admin privilege and group context
    if chat_id < 0:
        if not _check(update, context):
            return

    message = "Oh.. Okay, I will not send you any more news updates! " \
              "If you change your mind and you want to receive messages " \
              "from me again use /start command again!"
    update.message.reply_text(message)


def loop_parse(_):
    bp = BatchProcess(db=db, bot=dp.bot)
    bp.run()
    job_queue.run_once(callback=loop_parse, when=15, name='loop_feed')


def main():
    # Create the Updater and pass it your bot's token.
    dp.add_handler(CommandHandler(['start', 'help'], start))
    dp.add_handler(CommandHandler('welcome', set_welcome, pass_args=True))
    dp.add_handler(CommandHandler('goodbye', set_goodbye, pass_args=True))
    dp.add_handler(CommandHandler('disableWelcome', disable_welcome))
    dp.add_handler(CommandHandler('disableGoodbye', disable_goodbye))
    dp.add_handler(CommandHandler("lock", lock))
    dp.add_handler(CommandHandler("unlock", unlock))
    dp.add_handler(CommandHandler("quiet", quiet))
    dp.add_handler(CommandHandler("unquiet", unquiet))
    dp.add_handler(CommandHandler("me", get_user_info))
    dp.add_handler(CommandHandler('msg', msg, pass_args=True))

    dp.add_handler(CommandHandler('addurl', add_url, pass_args=True))
    dp.add_handler(CommandHandler('removeurl', remove_url, pass_args=True))
    dp.add_handler(CommandHandler('getkey', get_key, pass_args=True))
    dp.add_handler(CommandHandler('removekey', remove_key, pass_args=True))
    dp.add_handler(CommandHandler('getuser', get_chat_by_username, pass_args=True))
    dp.add_handler(CommandHandler('listurl', list_url))
    dp.add_handler(CommandHandler('allurl', all_url))
    dp.add_handler(CommandHandler('owner', _introduce))

    dp.add_handler(CommandHandler('stop', stop))

    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_chat_members))
    dp.add_handler(MessageHandler(Filters.status_update.left_chat_member, left_chat_member))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_title, new_chat_title))
    # dp.add_handler(MessageHandler(Filters.status_update, empty_message))
    # dp.add_handler(MessageHandler(Filters.all, empty_message))

    # dp.add_error_handler(error)

    loop_parse(dp)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    logger.info(f"Starting bot {__name__}")
    main()
