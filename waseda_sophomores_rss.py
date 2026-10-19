import os
import json
import time
import hashlib
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://www.wasedarugby.com/list/member/?gakunen=2"

STATE_FILE = "waseda_sophomores_state.json"
RSS_FILE = "waseda_sophomores.xml"

FEED_TITLE = "早稲田大学ラグビー蹴球部 2年生選手 更新"
FEED_DESCRIPTION = (
    "早稲田大学ラグビー蹴球部公式サイトの"
    "2年生選手一覧の変更監視"
)

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}


def clean_text(text):
    return " ".join(text.split()).strip()


def fetch_page():
    last_error = None

    for attempt in range(1, 4):
        try:
            print(
                f"取得試行 {attempt}/3: {SOURCE_URL}"
            )

            response = requests.get(
                SOURCE_URL,
                headers=HEADERS,
                timeout=30
            )

            print(
                f"HTTP: {response.status_code} / "
                f"取得バイト数: {len(response.content)} / "
                f"最終URL: {response.url}"
            )

            response.raise_for_status()
            response.encoding = "utf-8"

            return response.text

        except Exception as e:
            last_error = e

            print(f"取得失敗: {e}")

            if attempt < 3:
                print("10秒待って再試行します。")
                time.sleep(10)

    raise RuntimeError(
        f"ページを取得できませんでした: {last_error}"
    )


def get_text(element, selector):
    target = element.select_one(selector)

    if not target:
        return ""

    return clean_text(
        target.get_text(
            " ",
            strip=True
        )
    )


def parse_players(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    players = {}

    for player in soup.select("div.player"):
        grade = get_text(
            player,
            ".gakunen"
        )

        if grade != "2年":
            continue

        name_element = player.select_one(
            ".player-name a"
        )

        if not name_element:
            continue

        name = clean_text(
            name_element.get_text(
                " ",
                strip=True
            )
        )

        link = name_element.get(
            "href",
            ""
        ).strip()

        position = get_text(
            player,
            ".position"
        )

        hiragana = get_text(
            player,
            ".hiragana"
        )

        height = get_text(
            player,
            ".height"
        ).rstrip("/").strip()

        weight = get_text(
            player,
            ".weight"
        )

        # 選手は身長・体重を持つ。
        # スタッフは通常この情報を持たないため除外する。
        if not height and not weight:
            continue

        if not name or not link:
            continue

        players[link] = {
            "name": name,
            "hiragana": hiragana,
            "position": position,
            "grade": grade,
            "height": height,
            "weight": weight,
            "link": link,
        }

    return players


def load_state():
    if not os.path.exists(
        STATE_FILE
    ):
        return None

    with open(
        STATE_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def save_state(players):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            players,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_rss_items():
    items = []

    if not os.path.exists(
        RSS_FILE
    ):
        return items

    try:
        tree = ET.parse(
            RSS_FILE
        )

        root = tree.getroot()

        for item in root.findall(
            "./channel/item"
        ):
            title = item.findtext(
                "title",
                ""
            )

            link = item.findtext(
                "link",
                SOURCE_URL
            )

            guid = item.findtext(
                "guid",
                ""
            )

            description = item.findtext(
                "description",
                ""
            )

            pub_date = item.findtext(
                "pubDate",
                ""
            )

            try:
                published = parsedate_to_datetime(
                    pub_date
                )

                if published.tzinfo is None:
                    published = published.replace(
                        tzinfo=JST
                    )

            except Exception:
                continue

            items.append({
                "title": title,
                "link": link,
                "guid": guid,
                "description": description,
                "published": published,
            })

    except Exception as e:
        print(
            f"既存RSS読込エラー: {e}"
        )

    return items


def make_event(
    title,
    link,
    description,
    now
):
    raw = (
        f"{now.isoformat()}|"
        f"{title}|"
        f"{link}|"
        f"{description}"
    )

    guid = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()

    return {
        "title": title,
        "link": link,
        "guid": guid,
        "description": description,
        "published": now,
    }


def describe_player(player):
    parts = []

    if player.get("position"):
        parts.append(
            f"ポジション: {player['position']}"
        )

    if player.get("height"):
        parts.append(
            f"身長: {player['height']}"
        )

    if player.get("weight"):
        parts.append(
            f"体重: {player['weight']}"
        )

    if player.get("hiragana"):
        parts.append(
            f"読み: {player['hiragana']}"
        )

    return " / ".join(parts)


def compare_players(
    old_players,
    new_players
):
    events = []

    now = datetime.now(JST)

    old_links = set(
        old_players.keys()
    )

    new_links = set(
        new_players.keys()
    )

    added = new_links - old_links
    removed = old_links - new_links
    common = old_links & new_links

    for link in sorted(
        added,
        key=lambda x: new_players[x]["name"]
    ):
        player = new_players[link]

        title = (
            f"【追加】"
            f"{player['name']} "
            f"（{player['position']}）"
        )

        description = (
            "2年生選手一覧に追加されました。\n"
            + describe_player(player)
        )

        events.append(
            make_event(
                title,
                link,
                description,
                now
            )
        )

    for link in sorted(
        removed,
        key=lambda x: old_players[x]["name"]
    ):
        player = old_players[link]

        title = (
            f"【削除】"
            f"{player['name']} "
            f"（{player['position']}）"
        )

        description = (
            "2年生選手一覧から削除されました。\n"
            "削除前: "
            + describe_player(player)
        )

        events.append(
            make_event(
                title,
                SOURCE_URL,
                description,
                now
            )
        )

    fields = [
        ("name", "氏名"),
        ("hiragana", "読み"),
        ("position", "ポジション"),
        ("grade", "学年"),
        ("height", "身長"),
        ("weight", "体重"),
    ]

    for link in sorted(
        common,
        key=lambda x: new_players[x]["name"]
    ):
        old = old_players[link]
        new = new_players[link]

        changes = []

        for key, label in fields:
            old_value = old.get(
                key,
                ""
            )

            new_value = new.get(
                key,
                ""
            )

            if old_value != new_value:
                changes.append(
                    f"{label}: "
                    f"{old_value or 'なし'}"
                    f" → "
                    f"{new_value or 'なし'}"
                )

        if changes:
            title = (
                f"【変更】"
                f"{new['name']}"
            )

            description = (
                "2年生選手情報が変更されました。\n"
                + "\n".join(changes)
            )

            events.append(
                make_event(
                    title,
                    link,
                    description,
                    now
                )
            )

    return events


def write_rss(items):
    rss = ET.Element(
        "rss",
        version="2.0"
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = FEED_TITLE

    ET.SubElement(
        channel,
        "link"
    ).text = SOURCE_URL

    ET.SubElement(
        channel,
        "description"
    ).text = FEED_DESCRIPTION

    ET.SubElement(
        channel,
        "language"
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        datetime.now(JST)
    )

    items.sort(
        key=lambda x: x["published"],
        reverse=True
    )

    for data in items:
        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = data["title"]

        ET.SubElement(
            item,
            "link"
        ).text = data["link"]

        guid = ET.SubElement(
            item,
            "guid"
        )

        guid.set(
            "isPermaLink",
            "false"
        )

        guid.text = data["guid"]

        ET.SubElement(
            item,
            "pubDate"
        ).text = format_datetime(
            data["published"]
        )

        ET.SubElement(
            item,
            "description"
        ).text = data["description"]

    tree = ET.ElementTree(
        rss
    )

    try:
        ET.indent(
            tree,
            space="  "
        )
    except AttributeError:
        pass

    tree.write(
        RSS_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    print(
        "=" * 70
    )

    print(
        "早稲田大学ラグビー蹴球部 "
        "2年生選手 変更監視RSS"
    )

    print(
        "=" * 70
    )

    old_state = load_state()

    if old_state is None:
        print(
            "既存状態: なし（初回実行）"
        )
    else:
        print(
            f"既存状態: {len(old_state)}人"
        )

    try:
        html = fetch_page()

        new_state = parse_players(
            html
        )

        print(
            f"現在の2年生選手: "
            f"{len(new_state)}人"
        )

        if not new_state:
            raise RuntimeError(
                "2年生選手を"
                "1人も抽出できませんでした。"
            )

        print()

        for player in new_state.values():
            print(
                f"{player['name']} / "
                f"{player['position']} / "
                f"{player['height']} / "
                f"{player['weight']}"
            )

        existing_items = load_rss_items()

        if old_state is None:
            print()
            print(
                "初回実行のため、"
                "現在の一覧を基準データとして保存します。"
            )

            print(
                "変更通知は発生させません。"
            )

            events = []

        else:
            events = compare_players(
                old_state,
                new_state
            )

            print()
            print(
                f"検出した変更: "
                f"{len(events)}件"
            )

            for event in events:
                print(
                    event["title"]
                )

        all_items = (
            events
            + existing_items
        )

        unique_items = []
        seen_guids = set()

        for item in all_items:
            if item["guid"] in seen_guids:
                continue

            seen_guids.add(
                item["guid"]
            )

            unique_items.append(
                item
            )

        write_rss(
            unique_items
        )

        save_state(
            new_state
        )

        print()

        print(
            f"状態保存: "
            f"{STATE_FILE} "
            f"({len(new_state)}人)"
        )

        print(
            f"RSS保存: "
            f"{RSS_FILE} "
            f"({len(unique_items)}件)"
        )

    except Exception:
        print()

        print(
            "取得・解析に失敗したため、"
            "既存の状態ファイルとRSSは"
            "変更しません。"
        )

        raise


if __name__ == "__main__":
    main()