import logging
from datetime import timedelta

from multiprocessing.dummy import Pool as ThreadPool
from threading import Thread as RunningThread

import threading

from telegram.error import BadRequest, TelegramError
from telegram.vendor.ptb_urllib3.urllib3.exceptions import ConnectTimeoutError

from util.datehandler import DateHandler
from util.feedhandler import FeedHandler

logger = logging.getLogger(__name__)
logging.getLogger('util.processing').setLevel(logging.ERROR)


class BatchProcess(threading.Thread):

    def __init__(self, db, bot):
        RunningThread.__init__(self)

        self._finished = threading.Event()
        self.db = db
        self.bot = bot

    def run(self):
        logger.info(f'Start processing {self.bot.username}')
        if self._finished.isSet():
            return
        self.parse_parallel()

    def parse_parallel(self):
        if not self._finished.isSet():
            time_started = DateHandler.datetime.now()
            urls = self.db.get_urls_activated()
            threads = 1
            pool = ThreadPool(threads)
            pool.map(self.update_feed, urls)
            pool.close()
            pool.join()

            time_ended = DateHandler.datetime.now()
            duration = time_ended - time_started
            info_bot = self.bot.get_me()
            bot = info_bot.first_name
            logger.warning(f"Finished updating! Parsed {str(len(urls))} rss feeds in {str(duration)}! {bot}")

    def update_feed(self, url):
        if not self._finished.isSet():
            try:
                get_url_info = self.db.get_update_url(url)
                last_url = get_url_info['last_url']
                date_last_url = DateHandler.parse_datetime(get_url_info['last_update']) + timedelta(days=-1)
                feed = FeedHandler.parse_feed(url, 4, date_last_url)
                for post in feed:
                    if not hasattr(post, "published") and not hasattr(post, "daily_liturgy"):
                        logger.warning('not published' + url)
                        continue
                    # for index, post in enumerate(feed):
                    date_published = DateHandler.parse_datetime(post.published)

                    if hasattr(post, "daily_liturgy"):
                        if date_published > date_last_url and post.link != last_url \
                                and post.daily_liturgy != '':
                            message = post.title + '\n' + post.daily_liturgy
                            result = self.send_newest_messages(message, url)
                            if post == feed[-1] and result:
                                self.update_url(url=url, last_update=date_published, last_url=post.link)
                    elif date_published > date_last_url and post.link != last_url:
                        message = post.title + '\n' + post.link
                        result = self.send_newest_messages(message, url)
                        if result:
                            self.update_url(url=url, last_update=date_published, last_url=post.link)
                    else:
                        pass
                return True, url
            except TypeError as e:
                logger.error(f"TypeError {url} {str(e)}")
                return False, url, 'update_feed'

            except TelegramError as e:
                logger.error(f"except update_feed TelegramError {url} {str(e)}")
                return False, url, 'update_feed'

    def update_url(self, url, last_update, last_url):
        if not self._finished.isSet():
            self.db.update_url(url=url, last_update=last_update, last_url=last_url)

    def send_newest_messages(self, message, url):
        if not self._finished.isSet():
            names_url = self.db.get_names_for_user_activated(url)
            for name in names_url:
                chat_id = int(self.db.get_value_name_key(name, 'chat_id'))
                if chat_id:
                    try:
                        self.bot.send_message(chat_id=chat_id, text=message, parse_mode='html')
                        return True
                    except ConnectTimeoutError as e:
                        logger.error(f"{str(e)}")
                        return False

                    except TelegramError as e:
                        logger.error(f"{str(e.message)} {str(chat_id)}")
                        # logger.info('Error ' + e + ' when send message for chat_id ' + str(chat_id))
                        self.errors(chat_id=chat_id, error=e)
                        continue

    def errors(self, chat_id, error):
        """ Error handling """
        try:
            if error.message in ['Chat not found']:
                logger.error(f"{str(self.db.disable_url_chat(chat_id))}")

                logger.error('disable chat_id %s from chat list' % chat_id)
                # logger.error("An error occurred: %s" % error)

        except ConnectTimeoutError as e:
            logger.error(f"error ConnectTimeoutError {str(e)}")
        except ValueError as e:
            logger.error(f"error ValueError {str(e)}")

    def stop(self):
        """Stop this thread"""
        self._finished.set()
