import email.utils
import http.cookiejar
from nullroute.core import *
from nullroute.misc import set_file_attrs, set_file_mtime
import os
import requests
from urllib.parse import urljoin

def _file_nonempty(path):
    try:
        return os.stat(path).st_size > 0
    except FileNotFoundError:
        return False

def _http_date_to_unix(text):
    t = email.utils.parsedate_tz(text)
    t = email.utils.mktime_tz(t)
    return t

def file_ext(url):
    # throw away HTTP query, anchor
    if "#" in url:
        url = url.split("#")[0]
    if "?" in url:
        url = url.split("?")[0]
    # default for directories
    if url.endswith("/"):
        return "html"
    # get the basename
    url = url.split("/")[-1]
    url = url.split(".")
    if len(url) >= 3 and url[-2] == "tar":
        return url[-2] + "." + url[-1]
    elif len(url) >= 2:
        return url[-1]
    else:
        return "bin"

def _progress_bar(iterable, max_bytes, chunk_size):
    #hide_complete = (max_bytes < 1*1024*1024)
    hide_complete = True
    try:
        from tqdm import tqdm
        fmt = "{percentage:3.0f}% │{bar}│ {n_fmt} of {total_fmt}"
        bar = tqdm(iterable, total=max_bytes, unit="B",
                             unit_scale=True, unit_divisor=1024,
                             bar_format=fmt, ncols=80)
        with bar:
            for i in iterable:
                yield i
                bar.update(len(i))
    except ImportError:
        from nullroute.ui.progressbar import ProgressBar
        bar = ProgressBar(max_bytes=max_bytes)
        for i in iterable:
            yield i
            bar.incr(len(i))
        bar.end(hide_complete)

class Scraper(object):
    def __init__(self, output_dir="."):
        self.dir = output_dir
        if self.dir:
            os.makedirs(self.dir, exist_ok=True)

        self.ua = requests.Session()
        self.ua.mount("http://", requests.adapters.HTTPAdapter(max_retries=3))
        self.ua.mount("https://", requests.adapters.HTTPAdapter(max_retries=3))
        # unfortunately case-sensitive
        # https://www.modpagespeed.com/doc/experiment
        # currently only used by GamerCat scraper
        self.ua.headers["PageSpeed"] = "off"
        #self.ua.headers["X-PSA-Client-Options"] = "m=1"

        self.subclass_init()

    def subclass_init(self):
        pass

    def load_cookies(self, name):
        path = Env.find_cache_file("cookies/%s.txt" % name)
        Core.debug("loading cookies from %r" % path)
        cjar = http.cookiejar.LWPCookieJar(path)
        try:
            cjar.load()
        except FileNotFoundError:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.ua.cookies = cjar

    def store_cookies(self):
        self.ua.cookies.save()

    def get(self, url, *args, **kwargs):
        Core.debug("fetching %r" % url, skip=1)
        resp = self.ua.get(url, *args, **kwargs)
        resp.raise_for_status()
        return resp

    def get_page(self, url, *args, **kwargs):
        import bs4
        Core.debug("fetching %r" % url, skip=1)
        resp = self.ua.get(url, *args, **kwargs)
        resp.raise_for_status()
        page = bs4.BeautifulSoup(resp.content, "lxml")
        return page

    def save_file(self, url, name=None, referer=None,
                             output_dir=None, clobber=False,
                             progress=False, save_msg=None):
        if not name:
            name = os.path.basename(url)
        if output_dir:
            name = os.path.join(output_dir, name)

        if clobber:
            pass
        elif _file_nonempty(name):
            Core.debug("skipping %r" % url)
            return name

        hdr = {"Referer": referer or url}
        if progress:
            resp = self.get(url, headers=hdr, stream=True)
            with open(name + ".part", "wb") as fh:
                num_bytes = int(resp.headers.get("content-length"))
                chunk_size = 1024
                for chunk in _progress_bar(resp.iter_content(chunk_size),
                                           max_bytes=num_bytes,
                                           chunk_size=chunk_size):
                    fh.write(chunk)
            os.rename(name + ".part", name)
        else:
            resp = self.get(url, headers=hdr)
            with open(name, "wb") as fh:
                fh.write(resp.content)

        set_file_attrs(name, {
            "xdg.origin.url": resp.url,
            "xdg.referrer.url": resp.request.headers.get("Referer"),
            "http.ETag": resp.headers.get("ETag"),
            "http.Last-Modified": resp.headers.get("Last-Modified"),
        })

        mtime = resp.headers.get("Last-Modified")
        if mtime:
            set_file_mtime(name, _http_date_to_unix(mtime))

        if save_msg == True:
            Core.info("saved '%s'", name)
        elif save_msg:
            Core.info(save_msg)
        return name
