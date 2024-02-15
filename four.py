#!/usr/bin/env python3
import locale
import logging
import os
import re
import sys
import textwrap

import cloudscraper
from bs4 import BeautifulSoup
from bs4 import element

locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
WIDTH = 69
LINE = "-" * WIDTH


def leftpad(text: str, char: str = "-") -> str:
    return (WIDTH - len(str(text))) * char + str(text)


def log(*args, sep: str = "\n") -> None:
    logging.info(sep.join([str(x) for x in args if x]))


def write_url_to_file(url: str):
    url = url.split("#")[0]
    with open(STORED_URL, "w") as f:
        print(url, file=f)
    return url


class Post:  # {{{
    def __init__(
        self,
        tag: element.Tag,
    ):
        self.tag = tag

        self.id = int(self.tag["id"].strip("m"))
        self.author = self.tag.parent.div.span.span.text

        self.body = self.sanitise()
        self.cross_ids = self.get_cross_posts()

        if img := self.tag.parent.find("a", {"class": "fileThumb"}):
            self.img = "https:" + img["href"].strip()
        else:
            self.img = ""

        self.urls = []

    def display(self):
        log(
            # LINE,
            leftpad(self.id),
            self.img,
            self.body,
        )

    def get_cross_posts(self) -> list[int]:
        if not self.tag.a:
            return []

        return [
            int(x["href"].rsplit("p")[-1])
            for x in self.tag.find_all("a")
            # only cross posts have /
            if "#p" in x["href"]
            # edge case: ignore cross board
            and "://" not in x["href"]  # and x["href"][-1].isnumeric()
        ]

    def sanitise(
        self,
        use_nitter: bool = True,
    ) -> str:
        # .string should never be used as it completely misses greentext

        clean_lines = []

        # TODO: url fragment that is preceded by some text will not get merged

        for chunk in self.tag.get_text("\n").split("\n"):
            if chunk.startswith(">>>"):
                clean_lines.append("[https://boards.4chan.org" + chunk.strip(">") + "]")
            elif chunk.startswith(">>"):
                clean_lines.append("[" + chunk.replace(">>", url + "#p") + "]")
            elif chunk.startswith("http"):
                clean_lines.append(chunk)

            # line joining logic is quite convoluted:
            #
            # - only urls are undesirably broken by wbr
            # - there is no reliable way to tell when a url is complete
            # - all urls start with http, and url fragments usually have length 35 (hardcoded)

            elif (
                clean_lines
                and "http" in clean_lines[-1]
                and len(clean_lines[-1].split()[-1]) % 35 == 0
            ):
                clean_lines[-1] += chunk
            elif chunk:
                clean_lines.append(chunk)

        clean_lines = [
            (
                textwrap.fill(line, WIDTH)
                # if (" " in line and len(line) > WIDTH)
                if "http" not in line
                #
                else line
            )
            for line in clean_lines
        ]

        clean_lines = "\n".join(clean_lines)
        if use_nitter:
            clean_lines = clean_lines.replace("twitter.com", "nitter.net")
        return clean_lines


# }}}


def get_source(url: str) -> BeautifulSoup:
    scraper = cloudscraper.create_scraper()
    try:
        html = scraper.get(url)
    except ConnectionError:
        log("Timeout")
        sys.exit()

    if html.status_code != 200:
        log(html.status_code)
        sys.exit()

    return BeautifulSoup(html.content, "html.parser")


def find_new_thread(
    board: str,
    subject: str,
) -> str:
    """Search catalog for thread subject.

    Subject is matched case-sensitively."""

    # parsing index is fairly easy, if on page 1
    # catalog requires js, avoid at all costs

    base_url = f"https://boards.4chan.org/{board}"

    # iterate through pages until subject in source
    for page in range(1, 11):
        if page == 1:
            page = ""
        page_url = f"{base_url}/{page}"
        source = get_source(page_url)

        for thread in source.find_all(
            "span",
            {"class": "subject"},
        ):
            if (
                thread.string
                and (thread.string == subject or f"/{subject}/" in thread.string)
                and (thread_id := re.search(r"thread/\d+", thread.parent.prettify()))
            ):
                base_url = f"{base_url}/{thread_id.group(0)}"
                write_url_to_file(base_url)
                return base_url

    log("Thread not found:", subject)
    sys.exit()


# TODO: class Thread?
def main(url):
    source = get_source(url)

    if "Thread archived" in source.text:
        log("Archived, finding new thread...")
        url = find_new_thread(BOARD, SUBJECT)
        source = get_source(url)
        write_url_to_file(url)

    posts = source.find_all(
        "blockquote",
        {"class": "postMessage"},
        string=False,
    )

    log(leftpad(url))

    thread: dict[int, Post] = {}

    for raw_post in posts:
        post = Post(raw_post)

        # ignore named users
        if post.author != "Anonymous":
            continue

        post.display()

        # checking the contents of the cross post requires an extra scrape, so
        # just compare post IDs
        if (
            # post.cross_ids
            # ignore ids that were in the thread
            set(post.cross_ids) - set(thread)
            # ignore typical OP body
            and "Previous:" not in post.body
            # a lazy but good enough check
            and len(thread) > 300
            # and post.tag.a["href"].count(new_id) == 2
        ):
            new_id = max(set(post.cross_ids) - set(thread))

            log(f"WILL RELOAD: {new_id}")
            write_url_to_file(f"https://boards.4chan.org/{BOARD}/thread/{new_id}")

        # only done for crosspost checking
        thread[post.id] = post  # .body

    log(leftpad(url))


if __name__ == "__main__":
    _, BOARD, SUBJECT = sys.argv[:3]

    OUTFILE = f"/tmp/{SUBJECT.lower()}"
    STORED_URL = OUTFILE + ".url"

    if os.path.isfile(STORED_URL):
        with open(STORED_URL, encoding="UTF-8") as file:
            url = file.read().rstrip()
    else:
        url = find_new_thread(BOARD, SUBJECT)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        filemode="w+",
        filename=OUTFILE,
    )
    main(url)
