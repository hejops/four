#!/usr/bin/env python3
"""
https://github.com/4chan/4chan-API/tree/master/pages
"""
import locale
import logging
import os
import sys
import textwrap

import requests
from bs4 import BeautifulSoup

locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
WIDTH = 69
LINE = "-" * WIDTH


def leftpad(text: str, char: str = "-") -> str:
    return (WIDTH - len(str(text))) * char + str(text)


def write_url_to_file(url: str):
    url = url.split("#")[0]
    with open(STORED_URL, "w") as f:
        print(url, file=f)
    return url


def to_web_url(url):
    return url.replace("a.4cdn", "boards.4chan").removesuffix(".json")


class Post:  # {{{
    def __init__(
        self,
        d: dict,
    ):
        self.id = d["no"]
        self.author = d["name"]

        self.text = d.get("com")
        self.body = self.sanitise()
        self.cross_ids = self.get_cross_posts()
        # print(d)

        if img := d.get("tim"):
            self.img = f"https://i.4cdn.org/{BOARD}/{img}.jpg"
        else:
            self.img = ""

        self.urls = []

    def __str__(self):
        return "\n".join(
            str(x)
            for x in (
                leftpad(self.id),
                self.img,
                self.body,
            )
            if x
        )

    def display(self):
        logging.info(str(self))

    def get_cross_posts(self) -> list[int]:
        if not self.text or '"quotelink"' not in self.text:
            return []

        # {"com": '<a href="#p4817397" class="quotelink">'}

        return [
            int(x["href"].rsplit("p")[-1])
            for x in BeautifulSoup(self.text, "html.parser").find_all("a")
            # only cross posts have /
            if "#p" in x["href"]
            # edge case: ignore cross board
            and "://" not in x["href"]  # and x["href"][-1].isnumeric()
        ]

    def sanitise(
        self,
        # use_nitter: bool = True,
    ) -> str:
        if not self.text:
            return ""
        clean_lines = []

        # TODO: url fragment that is preceded by some text will not get merged

        # .string should never be used as it completely misses greentext
        for chunk in BeautifulSoup(self.text, "html.parser").get_text("\n").split("\n"):
            if chunk.startswith(">>>"):
                clean_lines.append(f'[https://boards.4chan.org{chunk.lstrip(">")}]')
            elif chunk.startswith(">>"):
                ref = f'{to_web_url(url)}#p{chunk.lstrip(">>")}'
                clean_lines.append(f"[{ref}]")
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
        # if use_nitter:
        #     clean_lines = clean_lines.replace("twitter.com", "nitter.net")
        return clean_lines


# }}}


class Thread:  # {{{
    def __init__(
        self,
        url: str,
    ):
        self.url = url
        # print(url)
        self.posts: dict[int, Post] = self.get_posts()
        self.url = to_web_url(self.url)

        # if "Thread archived" in source.text:
        #     log("Archived, finding new thread...")
        #     url = find_new_thread(BOARD, SUBJECT)
        #     source = get_source(url)
        #     write_url_to_file(url)

    def get_posts(self):
        resp = requests.get(url=self.url, timeout=3)
        if resp.status_code == 404:
            self.url = find_new_thread(BOARD, SUBJECT)
            resp = requests.get(url=self.url, timeout=3)
        posts = [Post(p) for p in resp.json()["posts"]]
        return {p.id: p for p in posts}

    def display(self):
        logging.info(leftpad(self.url))

        for post in self.posts.values():
            # ignore named users
            if post.author != "Anonymous":
                continue

            post.display()

            # checking the contents of the cross post requires an extra scrape, so
            # just compare post IDs
            if (
                # post.cross_ids
                # ignore ids that were in the thread
                set(post.cross_ids) - set(self.posts)
                # ignore typical OP body
                and "Previous:" not in post.body
                # a lazy but good enough check
                and len(self.posts) > 300
                # and post.tag.a["href"].count(new_id) == 2
            ):
                new_id = max(set(post.cross_ids) - set(self.posts))

                logging.info(f"WILL RELOAD: {new_id}")
                write_url_to_file(f"https://boards.4chan.org/{BOARD}/thread/{new_id}")

            # # only done for crosspost checking
            # thread[post.id] = post  # .body

        logging.info(leftpad(self.url))


# }}}


def find_new_thread(
    board: str,
    subject: str,
) -> str:
    """Search catalog for thread subject.

    Subject is matched case-sensitively."""

    base_url = f"https://a.4cdn.org/{board}/catalog.json"

    for page in requests.get(url=base_url, timeout=3).json():
        for thread in page["threads"]:
            if (
                (sub := thread.get("sub"))
                and (sub == subject or f"/{subject}/" in sub)
                # and (thread_id := re.search(r"thread/\d+", thread.parent.prettify()))
            ):
                base_url = f"https://a.4cdn.org/{board}/thread/{thread['no']}.json"
                write_url_to_file(base_url)
                return base_url

    logging.info("Thread not found: %s", subject)
    sys.exit()


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
    Thread(url).display()
